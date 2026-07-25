"""Изчисляване на предстоящите срокове към НАП, НСИ и Търговския регистър.

Модулът няма собствени таблици — всичко се извежда от календара и от профила на
компанията. Единственото четене от базата е проверката дали за даден месец има
вътреобщностни доставки (за VIES декларацията).

Единственото собствено състояние е таблицата `deadline_filings` — отметките
„подадено“. Календарът не може да ги изведе; всичко останало се изчислява.
``upcoming_deadlines`` ги чете с една заявка и обогатява ``DeadlineOut``.
"""
from __future__ import annotations

import calendar
import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.deadlines.holidays import next_working_day
from app.modules.deadlines.models import DeadlineFiling
from app.modules.deadlines.schemas import (
    AUTHORITY_NAP,
    AUTHORITY_NSI,
    AUTHORITY_TR,
    CATEGORY_ANNUAL_REPORT,
    CATEGORY_CORPORATE_TAX,
    CATEGORY_PAYROLL,
    CATEGORY_STATISTICS,
    CATEGORY_VAT,
    DeadlineOut,
)
from app.modules.vat.models import VatCode, VatDirection, VatEntry

MAX_DAYS_AHEAD = 400
DEFAULT_DAYS_AHEAD = 60

BG_MONTHS = (
    "януари", "февруари", "март", "април", "май", "юни",
    "юли", "август", "септември", "октомври", "ноември", "декември",
)
ROMAN_QUARTERS = {1: "I", 2: "II", 3: "III", 4: "IV"}

_NOTE_CIT_MONTHLY = (
    "ако нетните приходи от продажби за предходната година са над 3 000 000 лв."
)
_NOTE_INTRASTAT = "ако са надвишени праговете за деклариране по Интрастат"
_NOTE_PAYROLL = "ако компанията има наети лица или самоосигуряващи се"
_NOTE_VIES = "ако има ВОД или услуги по чл. 21, ал. 2 ЗДДС към лица от ЕС за периода"
_NOTE_WITHHOLDING = (
    "ако през тримесечието са начислени доходи на чуждестранни лица, "
    "облагаеми с данък при източника"
)


@dataclass(frozen=True)
class _Candidate:
    """Вътрешно представяне на срок преди преместването и филтрирането по прозорец."""

    key: str
    title: str
    description: str
    original_due_date: dt.date
    period_label: str
    category: str
    authority: str
    conditional: bool = False
    conditional_note: str | None = None


# ------------------------------------------------------------------ помощни
def _month_label(year: int, month: int) -> str:
    return f"{BG_MONTHS[month - 1]} {year}"


def _year_label(year: int) -> str:
    return f"{year} г."


def _quarter_label(year: int, quarter: int) -> str:
    return f"{ROMAN_QUARTERS[quarter]} тримесечие на {year} г."


def _polish(text: str) -> str:
    """Етикетите на годините/тримесечията завършват с „г.“ — маха двойната точка."""
    return text.replace("г..", "г.")


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def _iter_months(start: dt.date, end: dt.date):
    """Итерира (година, месец) включително граничните месеци."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


# ----------------------------------------------------------- месечни срокове
def _monthly_candidates(
    company: Company, year: int, month: int, *, ics_months: set[tuple[int, int]]
) -> list[_Candidate]:
    """Срокове, падащи през месец (year, month). Периодът е предходният месец."""
    period_year, period_month = _previous_month(year, month)
    period = _month_label(period_year, period_month)
    period_key = f"{period_year:04d}-{period_month:02d}"
    out: list[_Candidate] = []

    # ДДС задълженията важат само за регистрирани по ЗДДС лица.
    if company.is_vat_registered:
        out.append(
            _Candidate(
                key=f"vat-return:{period_key}",
                title="Справка-декларация по ЗДДС",
                description=(
                    f"Подаване на справка-декларацията по ЗДДС заедно с отчетните регистри "
                    f"(дневник покупки и дневник продажби) за {period} и внасяне на дължимия ДДС."
                ),
                original_due_date=dt.date(year, month, 14),
                period_label=period,
                category=CATEGORY_VAT,
                authority=AUTHORITY_NAP,
            )
        )
        # VIES: ако в ДДС дневника за периода има ВОД → срокът е сигурен, иначе е условен.
        has_ics = (period_year, period_month) in ics_months
        out.append(
            _Candidate(
                key=f"vies:{period_key}",
                title="VIES декларация",
                description=(
                    f"Подаване на VIES декларация за вътреобщностните доставки и услугите "
                    f"по чл. 21, ал. 2 ЗДДС към регистрирани лица от ЕС за {period}."
                ),
                original_due_date=dt.date(year, month, 14),
                period_label=period,
                category=CATEGORY_VAT,
                authority=AUTHORITY_NAP,
                conditional=not has_ics,
                conditional_note=None if has_ics else _NOTE_VIES,
            )
        )
        # Интрастат зависи от прагове, които системата не следи → винаги условен.
        out.append(
            _Candidate(
                key=f"intrastat:{period_key}",
                title="Интрастат декларация",
                description=(
                    f"Подаване на Интрастат декларация за {period} (изпращания и/или "
                    f"пристигания) при надвишени прагове за деклариране."
                ),
                original_due_date=dt.date(year, month, 14),
                period_label=period,
                category=CATEGORY_VAT,
                authority=AUTHORITY_NAP,
                conditional=True,
                conditional_note=_NOTE_INTRASTAT,
            )
        )

    # Осигуровки и данък по трудови правоотношения — системата не знае дали има наети лица.
    out.append(
        _Candidate(
            key=f"payroll-declarations:{period_key}",
            title="Декларации образец 1 и образец 6",
            description=(
                f"Подаване на декларация образец 1 (данни за осигуреното лице) и образец 6 "
                f"(дължими осигурителни вноски и данък по чл. 42 ЗДДФЛ) за {period} и "
                f"внасяне на удържаните суми."
            ),
            original_due_date=dt.date(year, month, 25),
            period_label=period,
            category=CATEGORY_PAYROLL,
            authority=AUTHORITY_NAP,
            conditional=True,
            conditional_note=_NOTE_PAYROLL,
        )
    )

    # Месечни авансови вноски по ЗКПО — само за месеците май–декември, до 15-о число.
    # Периодът тук е самият месец, за който се дължи вноската (не предходният).
    if 5 <= month <= 12:
        current = _month_label(year, month)
        out.append(
            _Candidate(
                key=f"cit-advance-monthly:{year:04d}-{month:02d}",
                title="Месечна авансова вноска по ЗКПО",
                description=(
                    f"Внасяне на месечната авансова вноска за корпоративен данък за {current}."
                ),
                original_due_date=dt.date(year, month, 15),
                period_label=current,
                category=CATEGORY_CORPORATE_TAX,
                authority=AUTHORITY_NAP,
                conditional=True,
                conditional_note=_NOTE_CIT_MONTHLY,
            )
        )
    return out


# -------------------------------------------------------- тримесечни срокове
def _quarterly_candidates(year: int, month: int) -> list[_Candidate]:
    """Срокове по тримесечия, падащи през месец (year, month)."""
    if month not in (1, 4, 7, 10):
        return []
    quarter = (month - 1) // 3  # тримесечието ПРЕДИ текущия месец
    quarter_year = year
    if quarter == 0:
        quarter, quarter_year = 4, year - 1
    period = _quarter_label(quarter_year, quarter)
    out: list[_Candidate] = []

    # Тримесечни авансови вноски по ЗКПО — за I и II тримесечие; за III не се дължи.
    if quarter in (1, 2) and quarter_year == year:
        out.append(
            _Candidate(
                key=f"cit-advance-quarterly:{quarter_year}-Q{quarter}",
                title="Тримесечна авансова вноска по ЗКПО",
                description=(
                    f"Внасяне на тримесечната авансова вноска за корпоративен данък за "
                    f"{period}. За третото тримесечие авансова вноска не се дължи."
                ),
                original_due_date=dt.date(year, month, 15),
                period_label=period,
                category=CATEGORY_CORPORATE_TAX,
                authority=AUTHORITY_NAP,
            )
        )

    # Данък при източника по чл. 195 ЗКПО — до края на месеца след тримесечието.
    out.append(
        _Candidate(
            key=f"withholding-tax:{quarter_year}-Q{quarter}",
            title="Данък при източника по чл. 195 ЗКПО",
            description=(
                f"Деклариране и внасяне на данъка, удържан при източника върху доходи на "
                f"чуждестранни лица, начислени през {period}."
            ),
            original_due_date=_month_bounds(year, month)[1],
            period_label=period,
            category=CATEGORY_CORPORATE_TAX,
            authority=AUTHORITY_NAP,
            conditional=True,
            conditional_note=_NOTE_WITHHOLDING,
        )
    )
    return out


# ------------------------------------------------------------ годишни срокове
def _annual_candidates(year: int) -> list[_Candidate]:
    """Годишни срокове, падащи през година `year`, за отчетната година `year - 1`."""
    reporting_year = year - 1
    period = _year_label(reporting_year)
    return [
        _Candidate(
            key=f"income-report-chl73:{reporting_year}",
            title="Справки по чл. 73 ЗДДФЛ",
            description=(
                f"Подаване на справката по чл. 73, ал. 1 (изплатени доходи на физически лица) "
                f"и справката по чл. 73, ал. 6 (доходи по трудови правоотношения) за {period}. "
                f"Файлът SPR73_6.xml се генерира от модула „Справки по чл. 73“ "
                f"(POST /api/v1/income-reports/chl73-6/xml)."
            ),
            original_due_date=dt.date(year, 2, 28),
            period_label=period,
            category=CATEGORY_PAYROLL,
            authority=AUTHORITY_NAP,
        ),
        _Candidate(
            key=f"cit-annual-return:{reporting_year}",
            title="Годишна данъчна декларация по чл. 92 ЗКПО",
            description=(
                f"Подаване на годишната данъчна декларация по чл. 92 ЗКПО за {period} и "
                f"внасяне на дължимия корпоративен данък."
            ),
            original_due_date=dt.date(year, 6, 30),
            period_label=period,
            category=CATEGORY_CORPORATE_TAX,
            authority=AUTHORITY_NAP,
        ),
        _Candidate(
            key=f"nsi-annual-report:{reporting_year}",
            title="Годишен отчет за дейността (НСИ)",
            description=(
                f"Подаване на годишния отчет за дейността за {period} в Националния "
                f"статистически институт."
            ),
            original_due_date=dt.date(year, 6, 30),
            period_label=period,
            category=CATEGORY_STATISTICS,
            authority=AUTHORITY_NSI,
        ),
        _Candidate(
            key=f"afr-publication:{reporting_year}",
            title="Публикуване на ГФО в Търговския регистър",
            description=(
                f"Публикуване на годишния финансов отчет за {period} в Търговския регистър "
                f"и регистъра на юридическите лица с нестопанска цел."
            ),
            original_due_date=dt.date(year, 9, 30),
            period_label=period,
            category=CATEGORY_ANNUAL_REPORT,
            authority=AUTHORITY_TR,
        ),
    ]


# ----------------------------------------------------------------- ВОД справка
def _months_with_ics_sales(
    db: Session, company_id, date_from: dt.date, date_to: dt.date
) -> set[tuple[int, int]]:
    """Месеците в интервала, за които има продажби с ДДС код, изискващ VIES (ВОД).

    Проверката е една заявка към ДДС дневника — вж. ``nap_export.render_vies``, което
    ползва същия признак (``VatCode.requires_vies``) за реда във VIES файла.
    """
    stmt = (
        select(VatEntry.document_date)
        .join(VatCode, VatCode.id == VatEntry.vat_code_id)
        .where(
            VatEntry.company_id == company_id,
            VatEntry.direction == VatDirection.SALE,
            VatCode.requires_vies.is_(True),
            VatEntry.document_date >= date_from,
            VatEntry.document_date <= date_to,
        )
    )
    return {(d.year, d.month) for d in db.scalars(stmt)}


# ------------------------------------------------------------------- публично
def upcoming_deadlines(
    db: Session,
    company: Company,
    *,
    reference_date: dt.date | None = None,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
    include_filed: bool = True,
) -> list[DeadlineOut]:
    """Предстоящите срокове в прозореца [reference_date, reference_date + days_ahead].

    Резултатът е сортиран по крайна дата възходящо (при равни дати — по ключ, за да е
    подредбата детерминирана).

    Отметнатите като подадени се връщат с ``filed=True``, а не се скриват:
    човек трябва да може да види какво вече е подал и да отмени грешна отметка.
    ``include_filed=False`` ги изключва — така мобилният клиент насрочва
    напомняния само за това, което още предстои.
    """
    today = reference_date or dt.date.today()
    days_ahead = max(1, min(days_ahead, MAX_DAYS_AHEAD))
    window_end = today + dt.timedelta(days=days_ahead)

    # Генерираме с един месец/година запас от двете страни: срок от края на месеца може
    # да се измести напред, а срок от началото — да попадне в прозореца след преместване.
    gen_from = today - dt.timedelta(days=40)
    gen_to = window_end + dt.timedelta(days=40)

    ics_months: set[tuple[int, int]] = set()
    if company.is_vat_registered:
        # Периодът на един срок е предходният месец → четем ДДС дневника с един месец назад.
        ics_from = dt.date(*_previous_month(gen_from.year, gen_from.month), 1)
        ics_months = _months_with_ics_sales(db, company.id, ics_from, gen_to)

    candidates: list[_Candidate] = []
    for year, month in _iter_months(gen_from, gen_to):
        candidates.extend(_monthly_candidates(company, year, month, ics_months=ics_months))
        candidates.extend(_quarterly_candidates(year, month))
    for year in range(gen_from.year, gen_to.year + 1):
        candidates.extend(_annual_candidates(year))

    # Една заявка за всички отметки на компанията — броят им е малък (по един
    # ред на подаден срок), затова не филтрираме по ключове.
    filings = {
        f.key: f.filed_at
        for f in db.scalars(
            select(DeadlineFiling).where(DeadlineFiling.company_id == company.id)
        )
    }

    result: list[DeadlineOut] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        due_date = next_working_day(candidate.original_due_date)
        if not (today <= due_date <= window_end):
            continue
        if candidate.key in seen_keys:  # предпазна мярка срещу дублиране на ключове
            continue
        filed_at = filings.get(candidate.key)
        if filed_at is not None and not include_filed:
            continue
        seen_keys.add(candidate.key)
        result.append(
            DeadlineOut(
                key=candidate.key,
                title=candidate.title,
                description=_polish(candidate.description),
                due_date=due_date,
                original_due_date=candidate.original_due_date,
                moved_for_holiday=due_date != candidate.original_due_date,
                period_label=candidate.period_label,
                category=candidate.category,
                authority=candidate.authority,
                conditional=candidate.conditional,
                conditional_note=candidate.conditional_note,
                days_remaining=(due_date - today).days,
                filed=filed_at is not None,
                filed_at=filed_at,
            )
        )
    result.sort(key=lambda d: (d.due_date, d.key))
    return result


# --------------------------------------------------------- отметки „подадено“


def mark_filed(
    db: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    note: str | None = None,
) -> DeadlineFiling:
    """Отмята срок като подаден. Повторното извикване обновява бележката.

    Идемпотентно нарочно: две натискания от два телефона не бива да дават
    грешка — резултатът е един и същ.
    """
    existing = db.scalar(
        select(DeadlineFiling).where(
            DeadlineFiling.company_id == company_id, DeadlineFiling.key == key
        )
    )
    if existing is not None:
        if note is not None:
            existing.note = note
        db.commit()
        db.refresh(existing)
        return existing

    filing = DeadlineFiling(
        company_id=company_id,
        key=key,
        filed_at=dt.datetime.now(dt.UTC),
        filed_by_id=user_id,
        note=note,
    )
    db.add(filing)
    db.commit()
    db.refresh(filing)
    return filing


def unmark_filed(db: Session, company_id: uuid.UUID, key: str) -> None:
    """Маха отметката. Липсваща отметка не е грешка — резултатът е същият."""
    filing = db.scalar(
        select(DeadlineFiling).where(
            DeadlineFiling.company_id == company_id, DeadlineFiling.key == key
        )
    )
    if filing is None:
        return
    db.delete(filing)
    db.commit()


def list_filings(db: Session, company_id: uuid.UUID) -> list[DeadlineFiling]:
    return list(
        db.scalars(
            select(DeadlineFiling)
            .where(DeadlineFiling.company_id == company_id)
            .order_by(DeadlineFiling.filed_at.desc())
        )
    )
