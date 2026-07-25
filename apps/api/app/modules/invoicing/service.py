"""Бизнес логика за фактуриране: чернова, издаване, осчетоводяване, ДДС."""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounting.models import Account, JournalType
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, post_entry
from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.invoicing.models import (
    ZERO,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    InvoiceType,
)
from app.modules.invoicing.schemas import InvoiceCreate
from app.modules.vat.models import VatCode, VatDirection
from app.modules.vat.schemas import VatEntryCreate
from app.modules.vat.service import create_vat_entry

_CENT = Decimal("0.01")

# Стандартни сметки за осчетоводяване на продажба (от стандартния сметкоплан).
_ACC_RECEIVABLE = "411"   # Клиенти
_ACC_REVENUE = "703"      # Приходи от услуги
_ACC_VAT_OUTPUT = "4532"  # Начислен ДДС на продажбите


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _acc(db: Session, company_id: uuid.UUID, code: str) -> Account:
    account = db.scalar(
        select(Account).where(Account.company_id == company_id, Account.code == code)
    )
    if account is None:
        raise _err(f"Липсва сметка {code} — инициализирай стандартния сметкоплан")
    return account


def _resolve_rate(db: Session, company_id: uuid.UUID, vat_code_id: uuid.UUID | None) -> Decimal:
    if vat_code_id is None:
        return ZERO
    code = db.get(VatCode, vat_code_id)
    if code is None or code.company_id != company_id:
        raise _err("ДДС кодът не съществува в тази компания")
    if code.direction != VatDirection.SALE:
        raise _err("ДДС кодът трябва да е за продажби (SALE)")
    return code.rate


def create_invoice(db: Session, company: Company, user_id: uuid.UUID, data: InvoiceCreate) -> Invoice:
    cp = db.get(Counterparty, data.counterparty_id)
    if cp is None or cp.company_id != company.id:
        raise _err("Контрагентът не съществува в тази компания")
    if cp.type not in (CounterpartyType.CUSTOMER, CounterpartyType.BOTH):
        raise _err("Контрагентът не е клиент")

    rate = _resolve_rate(db, company.id, data.vat_code_id)

    if data.original_invoice_id is not None:
        orig = db.get(Invoice, data.original_invoice_id)
        if orig is None or orig.company_id != company.id:
            raise _err("Оригиналната фактура не съществува в тази компания")

    lines: list[InvoiceLine] = []
    subtotal = ZERO
    for idx, raw in enumerate(data.lines, start=1):
        net = _q(raw.quantity * raw.unit_price)
        subtotal += net
        lines.append(
            InvoiceLine(line_no=idx, description=raw.description, quantity=raw.quantity,
                        unit_price=raw.unit_price, line_net=net)
        )
    vat_amount = _q(subtotal * rate / Decimal("100"))

    invoice = Invoice(
        company_id=company.id,
        counterparty_id=cp.id,
        invoice_type=data.invoice_type,
        series=data.series,
        issue_date=data.issue_date,
        tax_event_date=data.tax_event_date,
        due_date=data.due_date,
        currency=(data.currency or company.base_currency).upper(),
        vat_code_id=data.vat_code_id,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=subtotal + vat_amount,
        status=InvoiceStatus.DRAFT,
        notes=data.notes,
        original_invoice_id=data.original_invoice_id,
        created_by_id=user_id,
        lines=lines,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def list_invoices(db: Session, company_id: uuid.UUID) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice).where(Invoice.company_id == company_id).order_by(Invoice.created_at.desc())
        )
    )


def get_invoice(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.company_id != company_id:
        raise _err("Фактурата не е намерена", status.HTTP_404_NOT_FOUND)
    return inv


def _next_number(db: Session, company_id: uuid.UUID, series: str) -> int:
    current = db.scalar(
        select(func.max(Invoice.number)).where(
            Invoice.company_id == company_id, Invoice.series == series
        )
    )
    return (current or 0) + 1


def issue_invoice(db: Session, company: Company, invoice_id: uuid.UUID, user_id: uuid.UUID) -> Invoice:
    inv = get_invoice(db, company.id, invoice_id)
    if inv.status != InvoiceStatus.DRAFT:
        raise _err("Само чернова може да бъде издадена", status.HTTP_409_CONFLICT)

    inv.number = _next_number(db, company.id, inv.series)
    inv.tax_event_date = inv.tax_event_date or inv.issue_date

    # Счетоводен/данъчен ефект: фактура и дебитно известие → продажба;
    # кредитно известие → обратна операция (намалява прихода и ДДС). Проформа/аванс → само номер.
    _POSITIVE = (InvoiceType.INVOICE, InvoiceType.DEBIT_NOTE)
    _DOC_TYPE = {
        InvoiceType.INVOICE: "Фактура",
        InvoiceType.DEBIT_NOTE: "Дебитно известие",
        InvoiceType.CREDIT_NOTE: "Кредитно известие",
    }
    if inv.invoice_type in _POSITIVE or inv.invoice_type == InvoiceType.CREDIT_NOTE:
        recv = _acc(db, company.id, _ACC_RECEIVABLE)
        revenue = _acc(db, company.id, _ACC_REVENUE)
        positive = inv.invoice_type in _POSITIVE
        vat_sign = Decimal("1") if positive else Decimal("-1")

        if positive:
            entry_lines = [
                JournalLineIn(account_id=recv.id, debit=inv.total, credit=ZERO),
                JournalLineIn(account_id=revenue.id, debit=ZERO, credit=inv.subtotal),
            ]
        else:  # кредитно известие — огледална операция
            entry_lines = [
                JournalLineIn(account_id=revenue.id, debit=inv.subtotal, credit=ZERO),
                JournalLineIn(account_id=recv.id, debit=ZERO, credit=inv.total),
            ]
        if inv.vat_amount > ZERO:
            vat_out = _acc(db, company.id, _ACC_VAT_OUTPUT)
            if positive:
                entry_lines.insert(2, JournalLineIn(account_id=vat_out.id, debit=ZERO, credit=inv.vat_amount))
            else:
                entry_lines.insert(1, JournalLineIn(account_id=vat_out.id, debit=inv.vat_amount, credit=ZERO))

        entry = create_entry(
            db, company, user_id,
            JournalEntryCreate(
                document_date=inv.issue_date,
                journal=JournalType.SALES,
                document_type=_DOC_TYPE[inv.invoice_type],
                document_number=inv.full_number,
                description=f"{_DOC_TYPE[inv.invoice_type]} {inv.full_number}",
                lines=entry_lines,
            ),
        )
        post_entry(db, company.id, entry.id, user_id)
        inv.journal_entry_id = entry.id

        if inv.vat_code_id is not None and inv.subtotal > ZERO:
            cp = db.get(Counterparty, inv.counterparty_id)
            vat_entry = create_vat_entry(
                db, company.id, user_id,
                VatEntryCreate(
                    vat_code_id=inv.vat_code_id,
                    document_date=inv.issue_date,
                    tax_event_date=inv.tax_event_date,
                    document_number=inv.full_number,
                    counterparty_name=cp.name if cp else None,
                    counterparty_vat_number=cp.vat_number if cp else None,
                    tax_base=vat_sign * inv.subtotal,
                    vat_amount=vat_sign * inv.vat_amount,
                    journal_entry_id=entry.id,
                ),
            )
            inv.vat_entry_id = vat_entry.id

    inv.status = InvoiceStatus.ISSUED
    db.commit()
    db.refresh(inv)
    return inv


def cancel_invoice(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    inv = get_invoice(db, company_id, invoice_id)
    if inv.status != InvoiceStatus.DRAFT:
        raise _err("Издадена фактура не се анулира — издай кредитно известие", status.HTTP_409_CONFLICT)
    inv.status = InvoiceStatus.CANCELLED
    db.commit()
    db.refresh(inv)
    return inv
