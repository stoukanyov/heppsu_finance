"""Изчисление на едно възнаграждение — чиста логика, без БД и без FastAPI.

Тук няма нито един процент и нито един праг. Всичко идва отвън през `RateSet`, който
се пълни от параметрите, въведени в UI. Това е нарочно: данъчните изчисления са мястото,
където грешката е тиха и скъпа, а чистата функция се покрива с таблични тестове.

Ред на изчислението:

    1. Начислено      = основно (за отработените дни) + клас стаж + допълнителни + болничен
                        за сметка на работодателя
    2. Осиг. доход    = начисленото, вдигнато до минималния праг и орязано до максималния
    3. Вноски         = осиг. доход (или брутното) × процент, поотделно за лицето и работодателя
    4. Облагаем доход = брутно − вноските за сметка на лицето, които намаляват облагаемото
    5. Данък          = (облагаем доход − облекчения) × ставка
    6. Нето           = брутно − вноски на лицето − данък − други удръжки

Известни опростявания за първата версия (Q-012, за уточняване):
  · платеният годишен отпуск се плаща по дневната ставка от основното възнаграждение,
    а не по средно брутно от предходни месеци;
  · обезщетението за болничен за сметка на работодателя се начислява по същата дневна
    ставка, умножена по зададения процент.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.modules.deadlines.holidays import is_working_day

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


def q(amount: Decimal) -> Decimal:
    """Закръгляне до стотинка (математическо, нагоре при .5)."""
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def working_days_in_month(year: int, month: int) -> int:
    """Брой работни дни в месеца по българския календар (без уикенди и празници)."""
    days = calendar.monthrange(year, month)[1]
    return sum(1 for day in range(1, days + 1) if is_working_day(dt.date(year, month, day)))


# ==================================================================== вход
@dataclass(frozen=True)
class ContributionRate:
    """Един осигурителен фонд с процентите за двете страни."""

    code: str
    name: str
    employee_percent: Decimal = ZERO
    employer_percent: Decimal = ZERO
    on_insurance_income: bool = True   # False → начислява се върху брутното
    reduces_taxable_income: bool = True
    sort_order: int = 0


@dataclass(frozen=True)
class RateSet:
    """Параметрите, валидни за периода. Идват от `PayrollRateSet` в базата."""

    income_tax_percent: Decimal = ZERO
    max_insurance_income: Decimal | None = None
    default_min_insurance_income: Decimal = ZERO
    seniority_percent_per_year: Decimal = ZERO
    sick_employer_days: int = 0
    sick_employer_percent: Decimal = ZERO
    contributions: tuple[ContributionRate, ...] = ()


@dataclass(frozen=True)
class ContractInput:
    base_salary: Decimal
    seniority_years: Decimal = ZERO
    min_insurance_income: Decimal | None = None


@dataclass(frozen=True)
class PeriodInput:
    """Дните и допълнителните суми за конкретния месец."""

    working_days: int
    paid_leave_days: int = 0
    unpaid_leave_days: int = 0
    sick_employer_days: int = 0
    sick_fund_days: int = 0
    additional_amount: Decimal = ZERO
    tax_relief: Decimal = ZERO
    other_deductions: Decimal = ZERO

    @property
    def absent_days(self) -> int:
        return (
            self.paid_leave_days
            + self.unpaid_leave_days
            + self.sick_employer_days
            + self.sick_fund_days
        )

    @property
    def worked_days(self) -> int:
        return self.working_days - self.absent_days


# ==================================================================== изход
@dataclass
class ContributionAmount:
    code: str
    name: str
    base_amount: Decimal
    employee_amount: Decimal
    employer_amount: Decimal
    sort_order: int = 0


@dataclass
class PayrollResult:
    working_days: int
    worked_days: int
    base_amount: Decimal
    seniority_amount: Decimal
    additional_amount: Decimal
    sick_employer_amount: Decimal
    gross_amount: Decimal
    insurance_income: Decimal
    employee_contributions: Decimal
    employer_contributions: Decimal
    taxable_income: Decimal
    tax_relief: Decimal
    income_tax: Decimal
    other_deductions: Decimal
    net_amount: Decimal
    contributions: list[ContributionAmount] = field(default_factory=list)

    @property
    def total_employer_cost(self) -> Decimal:
        """Каква е пълната цена на служителя за работодателя."""
        return self.gross_amount + self.employer_contributions


# ==================================================================== изчисление
def _percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    return q(amount * percent / _HUNDRED)


def calculate(contract: ContractInput, period: PeriodInput, rates: RateSet) -> PayrollResult:
    """Изчислява един ред от ведомостта.

    Вдига `ValueError` при невалиден вход — извикващият го превръща в HTTP грешка.
    """
    if period.working_days <= 0:
        raise ValueError("Броят работни дни в месеца трябва да е положителен")
    if period.absent_days > period.working_days:
        raise ValueError(
            f"Дните отсъствие ({period.absent_days}) надхвърлят работните дни "
            f"в месеца ({period.working_days})"
        )
    if contract.base_salary < ZERO:
        raise ValueError("Основното възнаграждение не може да е отрицателно")

    working_days = period.working_days
    worked_days = period.worked_days
    daily_rate = contract.base_salary / Decimal(working_days)

    # 1. Начисления. Платените дни са отработените плюс платения годишен отпуск.
    paid_days = worked_days + period.paid_leave_days
    if paid_days == working_days:
        base_amount = q(contract.base_salary)   # цял месец — без дрейф от делението
    else:
        base_amount = q(daily_rate * Decimal(paid_days))

    seniority_amount = _percent_of(
        base_amount, rates.seniority_percent_per_year * contract.seniority_years
    )
    sick_employer_amount = _percent_of(
        q(daily_rate * Decimal(period.sick_employer_days)), rates.sick_employer_percent
    )
    gross_amount = q(
        base_amount + seniority_amount + period.additional_amount + sick_employer_amount
    )

    # 2. Осигурителен доход: минималният праг важи пропорционално на осигурените дни.
    insured_days = worked_days + period.paid_leave_days + period.sick_employer_days
    min_threshold = (
        contract.min_insurance_income
        if contract.min_insurance_income is not None
        else rates.default_min_insurance_income
    )
    min_applied = q(min_threshold * Decimal(insured_days) / Decimal(working_days))
    insurance_income = max(gross_amount, min_applied)
    if rates.max_insurance_income is not None:
        insurance_income = min(insurance_income, rates.max_insurance_income)

    # 3. Вноски по фондове.
    contributions: list[ContributionAmount] = []
    employee_total = ZERO
    employer_total = ZERO
    taxable_reduction = ZERO
    for rate in sorted(rates.contributions, key=lambda r: (r.sort_order, r.code)):
        base = insurance_income if rate.on_insurance_income else gross_amount
        employee_amount = _percent_of(base, rate.employee_percent)
        employer_amount = _percent_of(base, rate.employer_percent)
        employee_total += employee_amount
        employer_total += employer_amount
        if rate.reduces_taxable_income:
            taxable_reduction += employee_amount
        contributions.append(
            ContributionAmount(
                code=rate.code,
                name=rate.name,
                base_amount=base,
                employee_amount=employee_amount,
                employer_amount=employer_amount,
                sort_order=rate.sort_order,
            )
        )

    # 4-5. Облагаем доход и данък.
    taxable_income = max(ZERO, q(gross_amount - taxable_reduction))
    tax_base = max(ZERO, q(taxable_income - period.tax_relief))
    income_tax = _percent_of(tax_base, rates.income_tax_percent)

    # 6. Нето за получаване.
    net_amount = q(gross_amount - employee_total - income_tax - period.other_deductions)

    return PayrollResult(
        working_days=working_days,
        worked_days=worked_days,
        base_amount=base_amount,
        seniority_amount=seniority_amount,
        additional_amount=q(period.additional_amount),
        sick_employer_amount=sick_employer_amount,
        gross_amount=gross_amount,
        insurance_income=insurance_income,
        employee_contributions=q(employee_total),
        employer_contributions=q(employer_total),
        taxable_income=taxable_income,
        tax_relief=q(period.tax_relief),
        income_tax=income_tax,
        other_deductions=q(period.other_deductions),
        net_amount=net_amount,
        contributions=contributions,
    )
