"""Бизнес логика на счетоводното ядро: сметкоплан, периоди, операции."""
import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import business_today
from app.modules.accounting.models import (
    ZERO,
    Account,
    AccountingPeriod,
    AccountType,
    EntryStatus,
    FiscalYear,
    JournalEntry,
    JournalLine,
    PeriodStatus,
)
from app.modules.accounting.schemas import (
    AccountCreate,
    FiscalYearCreate,
    JournalEntryCreate,
)
from app.modules.companies.models import Company

_CENT = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ============================ Сметкоплан ============================
def create_account(db: Session, company_id: uuid.UUID, data: AccountCreate) -> Account:
    if data.parent_id is not None:
        parent = db.get(Account, data.parent_id)
        if parent is None or parent.company_id != company_id:
            raise _err("Родителската сметка не съществува в тази компания")
    account = Account(
        company_id=company_id,
        code=data.code,
        name=data.name,
        type=data.type,
        parent_id=data.parent_id,
        is_group=data.is_group,
        currency=data.currency.upper() if data.currency else None,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(f"Сметка с код {data.code} вече съществува", status.HTTP_409_CONFLICT)
    db.refresh(account)
    return account


def list_accounts(db: Session, company_id: uuid.UUID) -> list[Account]:
    return list(
        db.scalars(
            select(Account).where(Account.company_id == company_id).order_by(Account.code)
        )
    )


def seed_standard_chart(db: Session, company_id: uuid.UUID) -> int:
    """Създава стандартен български сметкоплан, ако компанията няма сметки.

    Q-001: конкретният национален сметкоплан подлежи на потвърждение — това е
    практически стартов шаблон, не нормативно задължителен списък.
    """
    existing = db.scalar(
        select(func.count()).select_from(Account).where(Account.company_id == company_id)
    )
    if existing:
        raise _err("Сметкопланът вече е инициализиран", status.HTTP_409_CONFLICT)

    by_code: dict[str, Account] = {}
    for code, name, acc_type, is_group, parent_code in STANDARD_BG_CHART:
        parent = by_code.get(parent_code) if parent_code else None
        account = Account(
            company_id=company_id,
            code=code,
            name=name,
            type=acc_type,
            is_group=is_group,
            parent_id=parent.id if parent else None,
        )
        db.add(account)
        db.flush()  # осигурява id за родителски връзки надолу
        by_code[code] = account
    db.commit()
    return len(by_code)


# ============================ Периоди ============================
def create_fiscal_year(db: Session, company_id: uuid.UUID, data: FiscalYearCreate) -> FiscalYear:
    start = data.start_date or dt.date(data.year, 1, 1)
    end = data.end_date or dt.date(data.year, 12, 31)
    fy = FiscalYear(company_id=company_id, year=data.year, start_date=start, end_date=end)
    db.add(fy)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _err(f"Фискална година {data.year} вече съществува", status.HTTP_409_CONFLICT)

    # 12 месечни периода (за календарна година).
    for month in range(1, 13):
        p_start = dt.date(data.year, month, 1)
        p_end = dt.date(data.year + (month // 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
        db.add(
            AccountingPeriod(
                company_id=company_id,
                fiscal_year_id=fy.id,
                code=f"{data.year}-{month:02d}",
                start_date=p_start,
                end_date=p_end,
                status=PeriodStatus.OPEN,
            )
        )
    db.commit()
    db.refresh(fy)
    return fy


def list_fiscal_years(db: Session, company_id: uuid.UUID) -> list[FiscalYear]:
    return list(
        db.scalars(
            select(FiscalYear)
            .where(FiscalYear.company_id == company_id)
            .order_by(FiscalYear.year.desc())
        )
    )


def find_period_for_date(db: Session, company_id: uuid.UUID, on_date: dt.date) -> AccountingPeriod | None:
    return db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.company_id == company_id,
            AccountingPeriod.start_date <= on_date,
            AccountingPeriod.end_date >= on_date,
        )
    )


def set_period_status(
    db: Session, company_id: uuid.UUID, period_id: uuid.UUID, new_status: PeriodStatus
) -> AccountingPeriod:
    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise _err("Периодът не е намерен", status.HTTP_404_NOT_FOUND)
    if period.status == PeriodStatus.LOCKED and new_status != PeriodStatus.LOCKED:
        raise _err("Окончателно заключен период не може да бъде отворен повторно", status.HTTP_409_CONFLICT)
    period.status = new_status
    db.commit()
    db.refresh(period)
    return period


# ============================ Счетоводни операции ============================
def _validate_and_build_lines(
    db: Session, company_id: uuid.UUID, data: JournalEntryCreate, rate: Decimal
) -> tuple[list[JournalLine], Decimal, Decimal]:
    lines: list[JournalLine] = []
    total_debit = ZERO
    total_credit = ZERO

    for idx, raw in enumerate(data.lines, start=1):
        debit = _q(raw.debit)
        credit = _q(raw.credit)
        # Точно едно от дебит/кредит трябва да е положително.
        if (debit > 0) == (credit > 0):
            raise _err(
                f"Ред {idx}: точно едно от дебит/кредит трябва да е положително число"
            )
        account = db.get(Account, raw.account_id)
        if account is None or account.company_id != company_id:
            raise _err(f"Ред {idx}: сметката не съществува в тази компания")
        if account.is_group:
            raise _err(f"Ред {idx}: не може да се осчетоводява по обобщаваща сметка {account.code}")
        if not account.is_active:
            raise _err(f"Ред {idx}: сметка {account.code} е неактивна")

        lines.append(
            JournalLine(
                line_no=idx,
                account_id=account.id,
                debit=debit,
                credit=credit,
                debit_base=_q(debit * rate),
                credit_base=_q(credit * rate),
                description=raw.description,
            )
        )
        total_debit += debit
        total_credit += credit

    if total_debit != total_credit:
        raise _err(
            f"Операцията не е балансирана: дебит {total_debit} ≠ кредит {total_credit}"
        )
    if total_debit == ZERO:
        raise _err("Операцията не може да бъде с нулева стойност")
    return lines, total_debit, total_credit


def create_entry(
    db: Session, company: Company, user_id: uuid.UUID, data: JournalEntryCreate
) -> JournalEntry:
    currency = (data.currency or company.base_currency).upper()
    rate = data.exchange_rate if currency != company.base_currency else Decimal("1.000000")

    period = find_period_for_date(db, company.id, data.document_date)
    if period is None:
        raise _err(
            "Няма счетоводен период за тази дата — създайте фискална година за годината на документа"
        )

    lines, _td, _tc = _validate_and_build_lines(db, company.id, data, rate)

    entry = JournalEntry(
        company_id=company.id,
        period_id=period.id,
        journal=data.journal,
        document_type=data.document_type,
        document_number=data.document_number,
        document_date=data.document_date,
        tax_event_date=data.tax_event_date,
        currency=currency,
        exchange_rate=rate,
        description=data.description,
        status=EntryStatus.DRAFT,
        created_by_id=user_id,
        lines=lines,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _next_entry_number(db: Session, company_id: uuid.UUID) -> int:
    current = db.scalar(
        select(func.max(JournalEntry.entry_number)).where(JournalEntry.company_id == company_id)
    )
    return (current or 0) + 1


def get_entry(db: Session, company_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.company_id != company_id:
        raise _err("Операцията не е намерена", status.HTTP_404_NOT_FOUND)
    return entry


def list_entries(db: Session, company_id: uuid.UUID) -> list[JournalEntry]:
    return list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.company_id == company_id)
            .order_by(JournalEntry.created_at.desc())
        )
    )


def post_entry(
    db: Session, company_id: uuid.UUID, entry_id: uuid.UUID, user_id: uuid.UUID
) -> JournalEntry:
    entry = get_entry(db, company_id, entry_id)
    if entry.status != EntryStatus.DRAFT:
        raise _err("Само чернова може да бъде осчетоводена", status.HTTP_409_CONFLICT)

    period = db.get(AccountingPeriod, entry.period_id)
    if period is None or period.status not in (PeriodStatus.OPEN, PeriodStatus.RESTRICTED):
        raise _err("Периодът не е отворен за осчетоводяване", status.HTTP_409_CONFLICT)

    # Защитна повторна проверка на баланса.
    if entry.total_debit != entry.total_credit or entry.total_debit == ZERO:
        raise _err("Небалансирана операция не може да бъде осчетоводена")

    entry.entry_number = _next_entry_number(db, company_id)
    entry.status = EntryStatus.POSTED
    entry.posting_date = business_today()
    entry.posted_by_id = user_id
    db.commit()
    db.refresh(entry)
    return entry


def reverse_entry(
    db: Session, company_id: uuid.UUID, entry_id: uuid.UUID, user_id: uuid.UUID
) -> JournalEntry:
    original = get_entry(db, company_id, entry_id)
    if original.status != EntryStatus.POSTED:
        raise _err("Само осчетоводена операция може да бъде сторнирана", status.HTTP_409_CONFLICT)

    period = db.get(AccountingPeriod, original.period_id)
    if period is None or period.status in (PeriodStatus.CLOSED, PeriodStatus.LOCKED):
        raise _err(
            "Периодът е приключен/заключен — сторното изисква коригиращ период",
            status.HTTP_409_CONFLICT,
        )

    reversal_lines = [
        JournalLine(
            line_no=line.line_no,
            account_id=line.account_id,
            debit=line.credit,          # разменени
            credit=line.debit,
            debit_base=line.credit_base,
            credit_base=line.debit_base,
            description=line.description,
        )
        for line in original.lines
    ]

    reversal = JournalEntry(
        company_id=company_id,
        period_id=original.period_id,
        journal=original.journal,
        document_type="СТОРНО",
        document_number=original.document_number,
        document_date=business_today(),
        tax_event_date=original.tax_event_date,
        currency=original.currency,
        exchange_rate=original.exchange_rate,
        description=f"Сторно на операция №{original.entry_number}",
        status=EntryStatus.REVERSAL,
        reverses_entry_id=original.id,
        created_by_id=user_id,
        posted_by_id=user_id,
        posting_date=business_today(),
        entry_number=_next_entry_number(db, company_id),
        lines=reversal_lines,
    )
    original.status = EntryStatus.REVERSED
    db.add(reversal)
    db.commit()
    db.refresh(reversal)
    return reversal


# ---------- Стандартен български сметкоплан (стартов шаблон, Q-001) ----------
# (code, name, type, is_group, parent_code)
STANDARD_BG_CHART: list[tuple[str, str, AccountType, bool, str | None]] = [
    # Клас 1 — Капитали
    ("10", "Капитал", AccountType.EQUITY, True, None),
    ("101", "Основен капитал", AccountType.EQUITY, False, "10"),
    ("117", "Резерви", AccountType.EQUITY, False, "10"),
    ("121", "Печалби и загуби от текущата година", AccountType.EQUITY, False, "10"),
    ("122", "Неразпределена печалба от минали години", AccountType.EQUITY, False, "10"),
    # Клас 2 — Дълготрайни активи
    ("20", "Дълготрайни материални активи", AccountType.ASSET, True, None),
    ("203", "Сгради", AccountType.ASSET, False, "20"),
    ("204", "Машини, съоръжения и оборудване", AccountType.ASSET, False, "20"),
    ("206", "Стопански инвентар", AccountType.ASSET, False, "20"),
    ("241", "Амортизация на ДМА", AccountType.ASSET, False, "20"),
    ("21", "Дълготрайни нематериални активи", AccountType.ASSET, True, None),
    ("214", "Софтуер и програмни продукти", AccountType.ASSET, False, "21"),
    ("242", "Амортизация на ДНА", AccountType.ASSET, False, "21"),
    # Клас 3 — Материални запаси
    ("30", "Материални запаси", AccountType.ASSET, True, None),
    ("302", "Материали", AccountType.ASSET, False, "30"),
    ("304", "Стоки", AccountType.ASSET, False, "30"),
    # Клас 4 — Разчети
    ("40", "Разчети с доставчици", AccountType.LIABILITY, True, None),
    ("401", "Доставчици", AccountType.LIABILITY, False, "40"),
    ("402", "Доставчици по аванси", AccountType.ASSET, False, "40"),
    ("41", "Разчети с клиенти", AccountType.ASSET, True, None),
    ("411", "Клиенти", AccountType.ASSET, False, "41"),
    ("412", "Клиенти по аванси", AccountType.LIABILITY, False, "41"),
    ("42", "Разчети с персонал и подотчетни лица", AccountType.LIABILITY, True, None),
    ("421", "Персонал — разчети по заплати", AccountType.LIABILITY, False, "42"),
    ("422", "Подотчетни лица", AccountType.ASSET, False, "42"),
    ("45", "Разчети с бюджета и НАП", AccountType.LIABILITY, True, None),
    ("4531", "Начислен ДДС на покупките (данъчен кредит)", AccountType.ASSET, False, "45"),
    ("4532", "Начислен ДДС на продажбите", AccountType.LIABILITY, False, "45"),
    ("4538", "ДДС за внасяне", AccountType.LIABILITY, False, "45"),
    ("4539", "ДДС за възстановяване", AccountType.ASSET, False, "45"),
    ("452", "Разчети за корпоративен данък", AccountType.LIABILITY, False, "45"),
    ("454", "Разчети за данъци върху доходите на ФЛ", AccountType.LIABILITY, False, "45"),
    ("46", "Разчети с осигурителни организации", AccountType.LIABILITY, True, None),
    ("461", "Разчети с осигурителни организации", AccountType.LIABILITY, False, "46"),
    # Клас 5 — Парични средства
    ("50", "Парични средства", AccountType.ASSET, True, None),
    ("501", "Каса в левове", AccountType.ASSET, False, "50"),
    ("502", "Каса във валута", AccountType.ASSET, False, "50"),
    ("503", "Разплащателна сметка в левове", AccountType.ASSET, False, "50"),
    ("504", "Разплащателна сметка във валута", AccountType.ASSET, False, "50"),
    # Клас 6 — Разходи
    ("60", "Разходи по икономически елементи", AccountType.EXPENSE, True, None),
    ("601", "Разходи за материали", AccountType.EXPENSE, False, "60"),
    ("602", "Разходи за външни услуги", AccountType.EXPENSE, False, "60"),
    ("603", "Разходи за амортизации", AccountType.EXPENSE, False, "60"),
    ("604", "Разходи за заплати", AccountType.EXPENSE, False, "60"),
    ("605", "Разходи за осигуровки", AccountType.EXPENSE, False, "60"),
    ("609", "Други разходи", AccountType.EXPENSE, False, "60"),
    # Клас 7 — Приходи
    ("70", "Приходи от продажби", AccountType.REVENUE, True, None),
    ("701", "Приходи от продажби на продукция", AccountType.REVENUE, False, "70"),
    ("702", "Приходи от продажби на стоки", AccountType.REVENUE, False, "70"),
    ("703", "Приходи от услуги", AccountType.REVENUE, False, "70"),
    ("709", "Други приходи", AccountType.REVENUE, False, "70"),
    # Задбалансови
    ("90", "Задбалансови сметки", AccountType.OFF_BALANCE, True, None),
]
