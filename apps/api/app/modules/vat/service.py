"""Бизнес логика на ДДС модула: кодове, регистри, контроли, декларация."""
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounting.models import AccountingPeriod
from app.modules.accounting.service import find_period_for_date
from app.modules.companies.models import Company
from app.modules.vat.models import VatCode, VatDirection, VatEntry
from app.tax_engine.registry import get_provider
from app.modules.vat.schemas import (
    DeclarationCell,
    VatCodeCreate,
    VatControl,
    VatDeclarationOut,
    VatEntryCreate,
    VatReturnOut,
    VatSideSummary,
)

_CENT = Decimal("0.01")
_TOLERANCE = Decimal("0.02")  # допустимо разминаване при закръгляне на ДДС


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ============================ ДДС кодове ============================
def seed_standard_vat_codes(db: Session, company_id: uuid.UUID) -> int:
    existing = db.scalar(
        select(func.count()).select_from(VatCode).where(VatCode.company_id == company_id)
    )
    if existing:
        raise _err("ДДС кодовете вече са инициализирани", status.HTTP_409_CONFLICT)
    for tpl in STANDARD_BG_VAT_CODES:
        db.add(VatCode(company_id=company_id, **tpl))
    db.commit()
    return len(STANDARD_BG_VAT_CODES)


def list_vat_codes(db: Session, company_id: uuid.UUID) -> list[VatCode]:
    return list(
        db.scalars(select(VatCode).where(VatCode.company_id == company_id).order_by(VatCode.code))
    )


def create_vat_code(db: Session, company_id: uuid.UUID, data: VatCodeCreate) -> VatCode:
    code = VatCode(company_id=company_id, **data.model_dump())
    db.add(code)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(f"ДДС код {data.code} вече съществува", status.HTTP_409_CONFLICT)
    db.refresh(code)
    return code


# ============================ ДДС записи ============================
def create_vat_entry(
    db: Session, company_id: uuid.UUID, user_id: uuid.UUID, data: VatEntryCreate
) -> VatEntry:
    vat_code = db.get(VatCode, data.vat_code_id)
    if vat_code is None or vat_code.company_id != company_id:
        raise _err("ДДС кодът не съществува в тази компания")
    if not vat_code.is_active:
        raise _err(f"ДДС код {vat_code.code} е неактивен")

    if vat_code.requires_vies and not data.counterparty_vat_number:
        raise _err(
            f"ДДС код {vat_code.code} изисква ДДС номер на контрагента (VIES)"
        )

    on_date = data.tax_event_date or data.document_date
    period = find_period_for_date(db, company_id, on_date)
    if period is None:
        raise _err("Няма счетоводен период за датата на данъчното събитие")

    expected_vat = _q(data.tax_base * vat_code.rate / Decimal("100"))
    if data.vat_amount is None:
        vat_amount = expected_vat
    else:
        vat_amount = _q(data.vat_amount)
        if abs(vat_amount - expected_vat) > _TOLERANCE:
            raise _err(
                f"ДДС ({vat_amount}) не съответства на очаквания при ставка "
                f"{vat_code.rate}% от основа {data.tax_base} (очаквано {expected_vat})"
            )

    if data.journal_entry_id is not None:
        from app.modules.accounting.models import JournalEntry

        je = db.get(JournalEntry, data.journal_entry_id)
        if je is None or je.company_id != company_id:
            raise _err("Свързаната счетоводна операция не съществува в тази компания")

    entry = VatEntry(
        company_id=company_id,
        period_id=period.id,
        vat_code_id=vat_code.id,
        direction=vat_code.direction,
        document_type=data.document_type,
        document_number=data.document_number,
        document_date=data.document_date,
        tax_event_date=data.tax_event_date,
        counterparty_name=data.counterparty_name,
        counterparty_vat_number=data.counterparty_vat_number,
        tax_base=_q(data.tax_base),
        vat_amount=vat_amount,
        journal_entry_id=data.journal_entry_id,
        created_by_id=user_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_vat_entries(
    db: Session,
    company_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    direction: VatDirection | None = None,
) -> list[VatEntry]:
    stmt = select(VatEntry).where(VatEntry.company_id == company_id)
    if period_id is not None:
        stmt = stmt.where(VatEntry.period_id == period_id)
    if direction is not None:
        stmt = stmt.where(VatEntry.direction == direction)
    return list(db.scalars(stmt.order_by(VatEntry.document_date, VatEntry.document_number)))


# ============================ Контроли и декларация ============================
def _period_or_404(db: Session, company_id: uuid.UUID, period_id: uuid.UUID) -> AccountingPeriod:
    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise _err("Периодът не е намерен", status.HTTP_404_NOT_FOUND)
    return period


def vat_period_controls(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> list[VatControl]:
    entries = list_vat_entries(db, company_id, period_id=period_id)
    controls: list[VatControl] = []
    seen: dict[tuple, list[uuid.UUID]] = defaultdict(list)

    for e in entries:
        rate = e.vat_code.rate
        expected = _q(e.tax_base * rate / Decimal("100"))
        if abs(e.vat_amount - expected) > _TOLERANCE:
            controls.append(
                VatControl(
                    level="ERROR",
                    code="VAT_MISMATCH",
                    message=(
                        f"Документ {e.document_number or '?'}: ДДС {e.vat_amount} ≠ очаквани "
                        f"{expected} при ставка {rate}%"
                    ),
                    vat_entry_id=e.id,
                )
            )
        if e.vat_code.requires_vies and not e.counterparty_vat_number:
            controls.append(
                VatControl(
                    level="ERROR",
                    code="MISSING_VIES",
                    message=f"Документ {e.document_number or '?'}: липсва ДДС номер (изисква VIES)",
                    vat_entry_id=e.id,
                )
            )
        if e.document_number:
            seen[(e.direction, e.document_number, e.counterparty_vat_number)].append(e.id)

    for (direction, doc_no, _vat), ids in seen.items():
        if len(ids) > 1:
            controls.append(
                VatControl(
                    level="WARNING",
                    code="DUPLICATE_DOCUMENT",
                    message=f"Възможен дубликат: документ {doc_no} се среща {len(ids)} пъти",
                    vat_entry_id=ids[-1],
                )
            )
    return controls


def get_vat_return(db: Session, company_id: uuid.UUID, period_id: uuid.UUID) -> VatReturnOut:
    period = _period_or_404(db, company_id, period_id)
    entries = list_vat_entries(db, company_id, period_id=period_id)

    sales = VatSideSummary(count=0, total_base=Decimal("0.00"), total_vat=Decimal("0.00"))
    purchases = VatSideSummary(
        count=0, total_base=Decimal("0.00"), total_vat=Decimal("0.00"), total_credit=Decimal("0.00")
    )

    for e in entries:
        if e.direction == VatDirection.SALE:
            sales.count += 1
            sales.total_base += e.tax_base
            sales.total_vat += e.vat_amount
        else:
            purchases.count += 1
            purchases.total_base += e.tax_base
            purchases.total_vat += e.vat_amount
            if e.vat_code.gives_credit:
                purchases.total_credit += e.vat_amount

    net = sales.total_vat - purchases.total_credit
    controls = vat_period_controls(db, company_id, period_id)

    return VatReturnOut(
        period_id=period.id,
        period_code=period.code,
        sales=sales,
        purchases=purchases,
        vat_payable=net if net > 0 else Decimal("0.00"),
        vat_refundable=-net if net < 0 else Decimal("0.00"),
        controls=controls,
        has_blocking_errors=any(c.level == "ERROR" for c in controls),
    )


# ============================ Справка-декларация (НАП) ============================
def _company_or_404(db: Session, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise _err("Компанията не е намерена", status.HTTP_404_NOT_FOUND)
    return company


def get_vat_declaration(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> VatDeclarationOut:
    period = _period_or_404(db, company_id, period_id)
    company = _company_or_404(db, company_id)
    entries = list_vat_entries(db, company_id, period_id=period_id)
    provider = get_provider(company.country)   # избор на данъчен плъгин по държава
    cells = provider.compute_declaration(entries)
    controls = vat_period_controls(db, company_id, period_id)
    return VatDeclarationOut(
        period_id=period.id,
        period_code=period.code.replace("-", "")[:6],
        company_name=company.name,
        company_vat_number=company.vat_number,
        cells=[DeclarationCell(**row) for row in cells.as_rows()],
        controls=controls,
        has_blocking_errors=any(c.level == "ERROR" for c in controls),
    )


def build_nap_files(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> tuple[bytes, str]:
    """Връща (zip_bytes, filename) с файловете за НАП за периода."""
    period = _period_or_404(db, company_id, period_id)
    company = _company_or_404(db, company_id)
    entries = list_vat_entries(db, company_id, period_id=period_id)
    provider = get_provider(company.country)   # избор на данъчен плъгин по държава
    zip_bytes, _cells = provider.build_filing_package(company, period.code, entries)
    per = period.code.replace("-", "")[:6]
    return zip_bytes, f"NAP-DDS-{per}.zip"


# ---------- Стандартни български ДДС кодове (стартов шаблон, Q-002) ----------
STANDARD_BG_VAT_CODES: list[dict] = [
    # Продажби
    {"code": "S20", "name": "Продажби с 20% ДДС", "direction": VatDirection.SALE,
     "rate": Decimal("20.00"), "gives_credit": False},
    {"code": "S09", "name": "Продажби с 9% ДДС", "direction": VatDirection.SALE,
     "rate": Decimal("9.00"), "gives_credit": False},
    {"code": "SICS", "name": "Вътреобщностна доставка (ВОД) 0%", "direction": VatDirection.SALE,
     "rate": Decimal("0.00"), "gives_credit": False, "requires_vies": True},
    {"code": "SEXP", "name": "Износ извън ЕС 0%", "direction": VatDirection.SALE,
     "rate": Decimal("0.00"), "gives_credit": False},
    {"code": "SEXM", "name": "Освободени доставки", "direction": VatDirection.SALE,
     "rate": Decimal("0.00"), "gives_credit": False},
    # Покупки
    {"code": "P20", "name": "Покупки с 20% ДДС — пълен данъчен кредит", "direction": VatDirection.PURCHASE,
     "rate": Decimal("20.00"), "gives_credit": True},
    {"code": "P09", "name": "Покупки с 9% ДДС — пълен данъчен кредит", "direction": VatDirection.PURCHASE,
     "rate": Decimal("9.00"), "gives_credit": True},
    {"code": "PNOCR", "name": "Покупки без право на данъчен кредит", "direction": VatDirection.PURCHASE,
     "rate": Decimal("20.00"), "gives_credit": False},
    {"code": "PICA", "name": "Вътреобщностно придобиване (ВОП) — самоначисляване", "direction": VatDirection.PURCHASE,
     "rate": Decimal("20.00"), "gives_credit": True, "requires_vies": True, "requires_protocol": True},
    {"code": "PREV", "name": "Самоначисляване по чл. 82 (обратно начисляване)", "direction": VatDirection.PURCHASE,
     "rate": Decimal("20.00"), "gives_credit": True, "requires_protocol": True},
]
