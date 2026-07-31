"""Бизнес логика за получени фактури (AP): чернова, осчетоводяване, ДДС."""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import business_today
from app.modules.accounting.models import Account, JournalType
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, post_entry
from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.documents.models import Document
from app.modules.purchases.models import (
    ZERO,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseStatus,
)
from app.modules.purchases.schemas import PurchaseCreate
from app.modules.vat.models import VatCode, VatDirection
from app.modules.vat.schemas import VatEntryCreate
from app.modules.vat.service import create_vat_entry

_CENT = Decimal("0.01")
_ACC_SUPPLIER = "401"          # Доставчици
_ACC_EXPENSE_DEFAULT = "602"   # Разходи за външни услуги
_ACC_VAT_INPUT = "4531"        # ДДС на покупките (данъчен кредит)


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _acc_by_code(db: Session, company_id: uuid.UUID, code: str) -> Account:
    account = db.scalar(
        select(Account).where(Account.company_id == company_id, Account.code == code)
    )
    if account is None:
        raise _err(f"Липсва сметка {code} — инициализирай стандартния сметкоплан")
    return account


def _vat_code(db: Session, company_id: uuid.UUID, vat_code_id: uuid.UUID | None) -> VatCode | None:
    if vat_code_id is None:
        return None
    code = db.get(VatCode, vat_code_id)
    if code is None or code.company_id != company_id:
        raise _err("ДДС кодът не съществува в тази компания")
    if code.direction != VatDirection.PURCHASE:
        raise _err("ДДС кодът трябва да е за покупки (PURCHASE)")
    return code


def create_purchase(db: Session, company: Company, user_id: uuid.UUID, data: PurchaseCreate) -> PurchaseInvoice:
    cp = db.get(Counterparty, data.counterparty_id)
    if cp is None or cp.company_id != company.id:
        raise _err("Контрагентът не съществува в тази компания")
    if cp.type not in (CounterpartyType.SUPPLIER, CounterpartyType.BOTH):
        raise _err("Контрагентът не е доставчик")

    code = _vat_code(db, company.id, data.vat_code_id)
    rate = code.rate if code else ZERO

    if data.expense_account_id is not None:
        acc = db.get(Account, data.expense_account_id)
        if acc is None or acc.company_id != company.id:
            raise _err("Разходната сметка не съществува в тази компания")
        if acc.is_group:
            raise _err(f"Сметка {acc.code} е обобщаваща — избери аналитична")
    if data.document_id is not None:
        doc = db.get(Document, data.document_id)
        if doc is None or doc.company_id != company.id:
            raise _err("Документът не съществува в тази компания")

    lines: list[PurchaseInvoiceLine] = []
    subtotal = ZERO
    for idx, raw in enumerate(data.lines, start=1):
        net = _q(raw.quantity * raw.unit_price)
        subtotal += net
        lines.append(
            PurchaseInvoiceLine(line_no=idx, description=raw.description, quantity=raw.quantity,
                                unit_price=raw.unit_price, line_net=net)
        )
    vat_amount = _q(subtotal * rate / Decimal("100"))

    inv = PurchaseInvoice(
        company_id=company.id,
        counterparty_id=cp.id,
        supplier_document_number=data.supplier_document_number,
        document_date=data.document_date,
        tax_event_date=data.tax_event_date,
        due_date=data.due_date,
        currency=(data.currency or company.base_currency).upper(),
        vat_code_id=data.vat_code_id,
        expense_account_id=data.expense_account_id,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=subtotal + vat_amount,
        status=PurchaseStatus.DRAFT,
        notes=data.notes,
        document_id=data.document_id,
        created_by_id=user_id,
        lines=lines,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def list_purchases(db: Session, company_id: uuid.UUID) -> list[PurchaseInvoice]:
    return list(
        db.scalars(
            select(PurchaseInvoice).where(PurchaseInvoice.company_id == company_id)
            .order_by(PurchaseInvoice.created_at.desc())
        )
    )


def get_purchase(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> PurchaseInvoice:
    inv = db.get(PurchaseInvoice, invoice_id)
    if inv is None or inv.company_id != company_id:
        raise _err("Фактурата не е намерена", status.HTTP_404_NOT_FOUND)
    return inv


def post_purchase(db: Session, company: Company, invoice_id: uuid.UUID, user_id: uuid.UUID) -> PurchaseInvoice:
    inv = get_purchase(db, company.id, invoice_id)
    if inv.status != PurchaseStatus.DRAFT:
        raise _err("Само чернова може да бъде осчетоводена", status.HTTP_409_CONFLICT)

    code = db.get(VatCode, inv.vat_code_id) if inv.vat_code_id else None
    creditable = bool(code) and code.gives_credit and inv.vat_amount > ZERO

    expense = db.get(Account, inv.expense_account_id) if inv.expense_account_id else _acc_by_code(db, company.id, _ACC_EXPENSE_DEFAULT)
    supplier = _acc_by_code(db, company.id, _ACC_SUPPLIER)

    # Данъчен кредит → ДДС отделно; без кредит → ДДС влиза в разхода.
    expense_debit = inv.subtotal if creditable else inv.total
    entry_lines = [JournalLineIn(account_id=expense.id, debit=expense_debit, credit=ZERO)]
    if creditable:
        vat_input = _acc_by_code(db, company.id, _ACC_VAT_INPUT)
        entry_lines.append(JournalLineIn(account_id=vat_input.id, debit=inv.vat_amount, credit=ZERO))
    entry_lines.append(JournalLineIn(account_id=supplier.id, debit=ZERO, credit=inv.total))

    inv.tax_event_date = inv.tax_event_date or inv.document_date
    entry = create_entry(
        db, company, user_id,
        JournalEntryCreate(
            document_date=inv.document_date,
            journal=JournalType.PURCHASES,
            document_type="Фактура (покупка)",
            document_number=inv.supplier_document_number,
            description=f"Покупка по фактура {inv.supplier_document_number}",
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
                document_date=inv.document_date,
                tax_event_date=inv.tax_event_date,
                document_number=inv.supplier_document_number,
                counterparty_name=cp.name if cp else None,
                counterparty_vat_number=cp.vat_number if cp else None,
                tax_base=inv.subtotal,
                vat_amount=inv.vat_amount,
                journal_entry_id=entry.id,
            ),
        )
        inv.vat_entry_id = vat_entry.id

    inv.status = PurchaseStatus.POSTED
    db.commit()
    db.refresh(inv)
    return inv


def cancel_purchase(db: Session, company_id: uuid.UUID, invoice_id: uuid.UUID) -> PurchaseInvoice:
    inv = get_purchase(db, company_id, invoice_id)
    if inv.status != PurchaseStatus.DRAFT:
        raise _err("Осчетоводена фактура не се анулира — ползвай сторно/кредитно известие", status.HTTP_409_CONFLICT)
    inv.status = PurchaseStatus.CANCELLED
    db.commit()
    db.refresh(inv)
    return inv


def import_ubl(
    db: Session, company: Company, user_id: uuid.UUID, xml: bytes, *,
    vat_code_id: uuid.UUID | None = None, expense_account_id: uuid.UUID | None = None,
) -> dict:
    """Чете входяща e-фактура (EN 16931 / UBL) и подготвя чернова покупка.

    Замества OCR: когато доставчикът прати структуриран документ, няма какво да се
    разпознава — данните вече са машинни и не искат проверка на разчитането.

    Доставчикът се търси по ЕИК и по ДДС номер. Ако не съществува, **не се създава
    мълчаливо**: връща се какво е прочетено и ясно указание какво липсва, защото
    автоматично създаден контрагент от чужд файл е тих източник на дубликати.
    """
    from app.modules.purchases.schemas import PurchaseCreate, PurchaseLineIn
    from app.tax_engine.export.registry import get_export_provider
    from app.tax_engine.export.ubl import parse_ubl

    provider = get_export_provider("UBL_BIS")
    report = provider.validate(xml)
    if not report.ok:
        raise _err(
            "Файлът не отговаря на EN 16931: " + "; ".join(i.message for i in report.errors[:5])
        )

    try:
        parsed = parse_ubl(xml)
    except Exception as exc:
        raise _err(f"Файлът не може да се прочете: {exc}") from exc

    supplier = None
    if parsed["supplier_eik"]:
        supplier = db.scalar(
            select(Counterparty).where(
                Counterparty.company_id == company.id,
                Counterparty.eik == parsed["supplier_eik"],
            )
        )
    if supplier is None and parsed["supplier_vat_number"]:
        supplier = db.scalar(
            select(Counterparty).where(
                Counterparty.company_id == company.id,
                Counterparty.vat_number == parsed["supplier_vat_number"],
            )
        )

    if supplier is None:
        return {
            "created": False,
            "reason": (
                f"Доставчикът „{parsed['supplier_name'] or '—'}“ "
                f"(ЕИК {parsed['supplier_eik'] or '—'}) не е в регистъра на контрагентите. "
                f"Добави го и повтори импорта."
            ),
            "parsed": parsed,
            "warnings": [i.message for i in report.warnings],
        }

    purchase = create_purchase(
        db, company, user_id,
        PurchaseCreate(
            counterparty_id=supplier.id,
            supplier_document_number=parsed["document_number"] or "БЕЗ НОМЕР",
            document_date=parsed["issue_date"] or business_today(),
            due_date=parsed["due_date"],
            currency=parsed["currency"],
            vat_code_id=vat_code_id,
            expense_account_id=expense_account_id,
            notes=parsed["notes"],
            lines=[
                PurchaseLineIn(
                    description=line["description"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                )
                for line in parsed["lines"]
            ],
        ),
    )
    return {
        "created": True,
        "purchase_id": purchase.id,
        "supplier": supplier.name,
        "document_number": parsed["document_number"],
        "total_in_file": str(parsed["total"]),
        "warnings": [i.message for i in report.warnings],
        "note": (
            "Черновата е създадена от структурирани данни — без OCR и без проверка на "
            "разчитането. Провери ДДС кода и разходната сметка преди осчетоводяване."
        ),
    }
