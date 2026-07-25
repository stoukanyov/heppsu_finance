"""Бизнес логика на ДДС модула: кодове, регистри, контроли, декларация."""
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounting.models import (
    Account,
    AccountingPeriod,
    EntryStatus,
    JournalEntry,
    JournalLine,
    JournalType,
)
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, find_period_for_date, post_entry
from app.modules.companies.models import Company
from app.modules.vat.models import (
    VatCode,
    VatDirection,
    VatEntry,
    VatPeriodClosing,
    VatPeriodRejection,
)
from app.modules.vat.schemas import (
    DeclarationCell,
    VatCodeCreate,
    VatControl,
    VatDeclarationOut,
    VatEntryCreate,
    VatPeriodClosingOut,
    VatPeriodRejectIn,
    VatPeriodSummaryOut,
    VatReturnOut,
    VatSideSummary,
)
from app.tax_engine.registry import get_provider

_POSTED_LIKE = (EntryStatus.POSTED, EntryStatus.REVERSED, EntryStatus.REVERSAL)

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

    if _closing_for_period(db, company_id, period.id) is not None:
        raise _err(
            f"ДДС периодът {period.code} е приключен — не се допускат нови ДДС записи",
            status.HTTP_409_CONFLICT,
        )

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


# ============================ Приключване на ДДС период ============================
_ACC_VAT_INPUT = "4531"       # Начислен ДДС на покупките (данъчен кредит) — актив
_ACC_VAT_OUTPUT = "4532"      # Начислен ДДС на продажбите — пасив
_ACC_VAT_PAYABLE = "4538"     # ДДС за внасяне — пасив
_ACC_VAT_REFUNDABLE = "4539"  # ДДС за възстановяване — актив


def _acc(db: Session, company_id: uuid.UUID, code: str) -> Account:
    account = db.scalar(
        select(Account).where(Account.company_id == company_id, Account.code == code)
    )
    if account is None:
        raise _err(f"Липсва сметка {code} — инициализирай стандартния сметкоплан")
    return account


def _closing_for_period(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> VatPeriodClosing | None:
    return db.scalar(
        select(VatPeriodClosing).where(
            VatPeriodClosing.company_id == company_id,
            VatPeriodClosing.period_id == period_id,
        )
    )


def _vat_account_balance(
    db: Session, company_id: uuid.UUID, code: str, period: AccountingPeriod
) -> Decimal:
    """Нетен оборот (дебит − кредит) по сметка за периода, от осчетоводените операции."""
    stmt = (
        select(
            func.coalesce(func.sum(JournalLine.debit_base), 0)
            - func.coalesce(func.sum(JournalLine.credit_base), 0)
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(
            JournalEntry.company_id == company_id,
            JournalEntry.status.in_(_POSTED_LIKE),
            Account.code == code,
            JournalEntry.document_date >= period.start_date,
            JournalEntry.document_date <= period.end_date,
        )
    )
    return _q(Decimal(db.scalar(stmt) or 0))


def get_vat_closing(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> VatPeriodClosing | None:
    _period_or_404(db, company_id, period_id)
    return _closing_for_period(db, company_id, period_id)


def close_vat_period(
    db: Session, company_id: uuid.UUID, user_id: uuid.UUID, period_id: uuid.UUID
) -> VatPeriodClosing:
    """Приключва ДДС периода: осчетоводява резултата и заключва периода за ДДС."""
    period = _period_or_404(db, company_id, period_id)
    company = _company_or_404(db, company_id)

    if _closing_for_period(db, company_id, period_id) is not None:
        raise _err(f"ДДС периодът {period.code} вече е приключен", status.HTTP_409_CONFLICT)

    controls = vat_period_controls(db, company_id, period_id)
    if any(c.level == "ERROR" for c in controls):
        raise _err("Има блокиращи грешки в контролите — приключването е спряно")

    # Салда по ДДС сметките за периода
    output_vat = -_vat_account_balance(db, company_id, _ACC_VAT_OUTPUT, period)  # пасив → кредитно салдо
    input_vat = _vat_account_balance(db, company_id, _ACC_VAT_INPUT, period)     # актив → дебитно салдо
    if output_vat < 0:
        output_vat = Decimal("0.00")
    if input_vat < 0:
        input_vat = Decimal("0.00")
    if output_vat == 0 and input_vat == 0:
        raise _err("Няма движения по ДДС сметките (4531/4532) за приключване")

    net = output_vat - input_vat  # >0 за внасяне, <0 за възстановяване

    lines: list[JournalLineIn] = []
    if output_vat > 0:
        lines.append(JournalLineIn(account_id=_acc(db, company_id, _ACC_VAT_OUTPUT).id,
                                   debit=output_vat, credit=Decimal("0.00")))
    if input_vat > 0:
        lines.append(JournalLineIn(account_id=_acc(db, company_id, _ACC_VAT_INPUT).id,
                                   debit=Decimal("0.00"), credit=input_vat))
    net_payable = Decimal("0.00")
    net_refundable = Decimal("0.00")
    if net > 0:
        net_payable = net
        lines.append(JournalLineIn(account_id=_acc(db, company_id, _ACC_VAT_PAYABLE).id,
                                   debit=Decimal("0.00"), credit=net))
    elif net < 0:
        net_refundable = -net
        lines.append(JournalLineIn(account_id=_acc(db, company_id, _ACC_VAT_REFUNDABLE).id,
                                   debit=-net, credit=Decimal("0.00")))

    entry = create_entry(
        db, company, user_id,
        JournalEntryCreate(
            document_date=period.end_date,
            journal=JournalType.CLOSING,
            document_type="ДДС приключване",
            document_number=f"ДДС-{period.code}",
            description=f"Приключване на ДДС период {period.code}",
            lines=lines,
        ),
    )
    post_entry(db, company_id, entry.id, user_id)

    closing = VatPeriodClosing(
        company_id=company_id,
        period_id=period_id,
        journal_entry_id=entry.id,
        output_vat=output_vat,
        input_vat=input_vat,
        net_payable=net_payable,
        net_refundable=net_refundable,
        closed_by_id=user_id,
    )
    db.add(closing)
    db.commit()
    db.refresh(closing)
    return closing


# ============ Списък с ДДС периоди, одобрение и отказ (мобилен клиент) ============
# Статуси на ДДС отчета за период — извеждат се от реалното състояние, не се пазят:
STATUS_OPEN = "OPEN"          # няма данни за деклариране / още няма какво да се одобрява
STATUS_READY = "READY"        # има данни и периодът не е приключен → чака одобрение
STATUS_APPROVED = "APPROVED"  # има VatPeriodClosing (одобрен чрез /close)
STATUS_REJECTED = "REJECTED"  # има запис за отказ и няма приключване


def _entry_totals_by_period(
    db: Session, company_id: uuid.UUID
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Суми (начислен ДДС, данъчен кредит) по период — от ДДС регистрите."""
    rows = db.execute(
        select(
            VatEntry.period_id,
            VatEntry.direction,
            VatCode.gives_credit,
            func.coalesce(func.sum(VatEntry.vat_amount), 0),
        )
        .join(VatCode, VatEntry.vat_code_id == VatCode.id)
        .where(VatEntry.company_id == company_id)
        .group_by(VatEntry.period_id, VatEntry.direction, VatCode.gives_credit)
    ).all()

    totals: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for period_id, direction, gives_credit, amount in rows:
        output_vat, input_vat = totals.get(period_id, (Decimal("0.00"), Decimal("0.00")))
        amount = _q(Decimal(amount or 0))
        if direction == VatDirection.SALE:
            output_vat += amount
        elif gives_credit:
            input_vat += amount
        totals[period_id] = (output_vat, input_vat)
    return totals


def _account_totals_by_period(
    db: Session, company_id: uuid.UUID
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Резервен източник: обороти по 4532/4531 от осчетоводените операции.

    Използва се за периоди без записи в ДДС регистрите (ДДС-то е дошло директно
    от счетоводни операции) — иначе отчетът би изглеждал празен в списъка.
    """
    rows = db.execute(
        select(
            JournalEntry.period_id,
            Account.code,
            func.coalesce(func.sum(JournalLine.debit_base), 0)
            - func.coalesce(func.sum(JournalLine.credit_base), 0),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(
            JournalEntry.company_id == company_id,
            JournalEntry.status.in_(_POSTED_LIKE),
            Account.code.in_((_ACC_VAT_OUTPUT, _ACC_VAT_INPUT)),
        )
        .group_by(JournalEntry.period_id, Account.code)
    ).all()

    totals: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for period_id, code, balance in rows:
        output_vat, input_vat = totals.get(period_id, (Decimal("0.00"), Decimal("0.00")))
        value = _q(Decimal(balance or 0))
        if code == _ACC_VAT_OUTPUT:
            output_vat = -value if value < 0 else Decimal("0.00")  # пасив → кредитно салдо
        else:
            input_vat = value if value > 0 else Decimal("0.00")    # актив → дебитно салдо
        totals[period_id] = (output_vat, input_vat)
    return totals


def _latest_rejections(
    db: Session, company_id: uuid.UUID
) -> dict[uuid.UUID, VatPeriodRejection]:
    """Последният отказ за всеки период (пази се цялата история)."""
    latest: dict[uuid.UUID, VatPeriodRejection] = {}
    rows = db.scalars(
        select(VatPeriodRejection)
        .where(VatPeriodRejection.company_id == company_id)
        .order_by(VatPeriodRejection.created_at)
    )
    for rejection in rows:
        latest[rejection.period_id] = rejection
    return latest


def _period_summary(
    period: AccountingPeriod,
    closing: VatPeriodClosing | None,
    rejection: VatPeriodRejection | None,
    totals: tuple[Decimal, Decimal],
) -> VatPeriodSummaryOut:
    if closing is not None:
        output_vat, input_vat = closing.output_vat, closing.input_vat
        net_payable = closing.net_payable - closing.net_refundable
        status_code = STATUS_APPROVED
    else:
        output_vat, input_vat = totals
        net_payable = output_vat - input_vat
        if rejection is not None:
            status_code = STATUS_REJECTED
        elif output_vat or input_vat:
            status_code = STATUS_READY
        else:
            status_code = STATUS_OPEN
    return VatPeriodSummaryOut(
        period_id=period.id,
        code=period.code,
        start_date=period.start_date,
        end_date=period.end_date,
        output_vat=_q(output_vat),
        input_vat=_q(input_vat),
        net_payable=_q(net_payable),
        status=status_code,
        closed_at=closing.created_at if closing is not None else None,
        rejection_reason=rejection.reason if (closing is None and rejection) else None,
    )


def list_vat_periods(db: Session, company_id: uuid.UUID) -> list[VatPeriodSummaryOut]:
    """Месечните ДДС отчети на компанията — най-новите първи."""
    periods = list(
        db.scalars(
            select(AccountingPeriod)
            .where(AccountingPeriod.company_id == company_id)
            .order_by(AccountingPeriod.start_date.desc(), AccountingPeriod.code.desc())
        )
    )
    closings = {
        c.period_id: c
        for c in db.scalars(
            select(VatPeriodClosing).where(VatPeriodClosing.company_id == company_id)
        )
    }
    rejections = _latest_rejections(db, company_id)
    entry_totals = _entry_totals_by_period(db, company_id)
    account_totals = _account_totals_by_period(db, company_id)
    zero = (Decimal("0.00"), Decimal("0.00"))

    return [
        _period_summary(
            period,
            closings.get(period.id),
            rejections.get(period.id),
            entry_totals.get(period.id) or account_totals.get(period.id) or zero,
        )
        for period in periods
    ]


def get_vat_period_summary(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID
) -> VatPeriodSummaryOut:
    period = _period_or_404(db, company_id, period_id)
    entry_totals = _entry_totals_by_period(db, company_id)
    account_totals = _account_totals_by_period(db, company_id)
    return _period_summary(
        period,
        _closing_for_period(db, company_id, period_id),
        _latest_rejections(db, company_id).get(period_id),
        entry_totals.get(period_id)
        or account_totals.get(period_id)
        or (Decimal("0.00"), Decimal("0.00")),
    )


def reject_vat_period(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    period_id: uuid.UUID,
    data: VatPeriodRejectIn,
) -> VatPeriodSummaryOut:
    """Връща ДДС периода за корекция (отказва одобрението)."""
    period = _period_or_404(db, company_id, period_id)

    if _closing_for_period(db, company_id, period_id) is not None:
        raise _err(
            f"ДДС периодът {period.code} вече е приключен — първо трябва да се отпуши "
            f"приключването (сторно на приключвателната операция), преди да се върне за корекция",
            status.HTTP_409_CONFLICT,
        )

    db.add(
        VatPeriodRejection(
            company_id=company_id,
            period_id=period_id,
            reason=data.reason,
            rejected_by_id=user_id,
        )
    )
    db.commit()
    return get_vat_period_summary(db, company_id, period_id)


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
