"""Таблични тестове на ядрото на ТРЗ изчислението (`payroll/calc.py`).

Тестовете са без БД и без HTTP — това е най-рисковата логика в модула и трябва да се
покрие с точни числа, а не с „минава без грешка". Ставките тук са произволни кръгли
числа: те идват от параметрите на потребителя, не от кода.
"""
import datetime as dt
from decimal import Decimal

import pytest

from app.modules.payroll.calc import (
    ContractInput,
    ContributionRate,
    PeriodInput,
    RateSet,
    calculate,
    working_days_in_month,
)

D = Decimal


def _rates(**overrides) -> RateSet:
    """Набор с два фонда: 10/12 % и 3.2/4.8 %, данък 10 %."""
    defaults = dict(
        income_tax_percent=D("10.00"),
        contributions=(
            ContributionRate("DOO", "Държавно обществено осигуряване", D("10.00"), D("12.00"), sort_order=1),
            ContributionRate("ZO", "Здравно осигуряване", D("3.20"), D("4.80"), sort_order=2),
        ),
    )
    defaults.update(overrides)
    return RateSet(**defaults)


def test_full_month_without_absences() -> None:
    result = calculate(
        ContractInput(base_salary=D("2000.00")),
        PeriodInput(working_days=21),
        _rates(),
    )

    assert result.worked_days == 21
    assert result.gross_amount == D("2000.00")
    assert result.insurance_income == D("2000.00")
    # 10 % + 3.2 % за сметка на лицето, 12 % + 4.8 % за сметка на работодателя
    assert result.employee_contributions == D("264.00")
    assert result.employer_contributions == D("336.00")
    assert result.taxable_income == D("1736.00")
    assert result.income_tax == D("173.60")
    assert result.net_amount == D("1562.40")
    assert result.total_employer_cost == D("2336.00")


def test_contribution_breakdown_is_per_fund() -> None:
    result = calculate(
        ContractInput(base_salary=D("2000.00")), PeriodInput(working_days=21), _rates()
    )

    by_code = {c.code: c for c in result.contributions}
    assert by_code["DOO"].employee_amount == D("200.00")
    assert by_code["DOO"].employer_amount == D("240.00")
    assert by_code["ZO"].employee_amount == D("64.00")
    assert by_code["ZO"].employer_amount == D("96.00")
    assert all(c.base_amount == D("2000.00") for c in result.contributions)


def test_maximum_insurance_income_caps_the_base() -> None:
    result = calculate(
        ContractInput(base_salary=D("5000.00")),
        PeriodInput(working_days=20),
        _rates(max_insurance_income=D("3400.00")),
    )

    assert result.gross_amount == D("5000.00")
    assert result.insurance_income == D("3400.00")   # орязан до тавана
    assert result.employee_contributions == D("448.80")  # 13.2 % от 3400
    # Данъкът е върху брутното минус вноските, не върху осигурителния доход.
    assert result.taxable_income == D("4551.20")
    assert result.income_tax == D("455.12")


def test_minimum_threshold_raises_insurance_income_above_gross() -> None:
    result = calculate(
        ContractInput(base_salary=D("500.00")),
        PeriodInput(working_days=21),
        _rates(default_min_insurance_income=D("933.00")),
    )

    assert result.gross_amount == D("500.00")
    assert result.insurance_income == D("933.00")
    assert result.employee_contributions == D("123.16")  # 93.30 + 29.86
    # Вноските се смятат върху прага, но данъкът — върху брутното намалено с тях.
    assert result.taxable_income == D("376.84")
    assert result.income_tax == D("37.68")
    assert result.net_amount == D("339.16")


def test_contract_threshold_overrides_the_default() -> None:
    result = calculate(
        ContractInput(base_salary=D("500.00"), min_insurance_income=D("1200.00")),
        PeriodInput(working_days=21),
        _rates(default_min_insurance_income=D("933.00")),
    )

    assert result.insurance_income == D("1200.00")


def test_unpaid_leave_reduces_pay_and_threshold_proportionally() -> None:
    result = calculate(
        ContractInput(base_salary=D("2100.00")),
        PeriodInput(working_days=21, unpaid_leave_days=3),
        _rates(default_min_insurance_income=D("2100.00")),
    )

    assert result.worked_days == 18
    assert result.base_amount == D("1800.00")       # 18 от 21 дни по 100
    # Прагът важи за 18 осигурени дни: 2100 × 18 / 21 = 1800
    assert result.insurance_income == D("1800.00")


def test_paid_leave_is_paid_and_insured() -> None:
    result = calculate(
        ContractInput(base_salary=D("2100.00")),
        PeriodInput(working_days=21, paid_leave_days=5),
        _rates(),
    )

    assert result.worked_days == 16
    assert result.base_amount == D("2100.00")   # платеният отпуск се плаща
    assert result.gross_amount == D("2100.00")


def test_seniority_bonus_is_percent_per_year() -> None:
    result = calculate(
        ContractInput(base_salary=D("1000.00"), seniority_years=D("10")),
        PeriodInput(working_days=20),
        _rates(seniority_percent_per_year=D("0.60")),
    )

    assert result.seniority_amount == D("60.00")   # 10 години × 0.6 %
    assert result.gross_amount == D("1060.00")


def test_sick_leave_paid_by_employer() -> None:
    result = calculate(
        ContractInput(base_salary=D("2000.00")),
        PeriodInput(working_days=20, sick_employer_days=3),
        _rates(sick_employer_days=3, sick_employer_percent=D("70.00")),
    )

    assert result.base_amount == D("1700.00")            # 17 отработени дни по 100
    assert result.sick_employer_amount == D("210.00")    # 3 × 100 × 70 %
    assert result.gross_amount == D("1910.00")


def test_additional_amount_and_other_deductions() -> None:
    result = calculate(
        ContractInput(base_salary=D("1000.00")),
        PeriodInput(working_days=20, additional_amount=D("200.00"), other_deductions=D("50.00")),
        _rates(),
    )

    assert result.gross_amount == D("1200.00")
    assert result.employee_contributions == D("158.40")
    assert result.income_tax == D("104.16")
    assert result.net_amount == D("887.44")   # 1200 − 158.40 − 104.16 − 50


def test_tax_relief_cannot_make_the_tax_negative() -> None:
    result = calculate(
        ContractInput(base_salary=D("1000.00")),
        PeriodInput(working_days=20, tax_relief=D("5000.00")),
        _rates(),
    )

    assert result.income_tax == D("0.00")
    assert result.net_amount == D("868.00")   # 1000 − 132


def test_contribution_on_gross_ignores_the_cap() -> None:
    rates = _rates(
        max_insurance_income=D("1000.00"),
        contributions=(
            ContributionRate("FUND", "Фонд върху брутното", D("5.00"), D("0.00"),
                             on_insurance_income=False, sort_order=1),
        ),
    )
    result = calculate(ContractInput(base_salary=D("2000.00")), PeriodInput(working_days=20), rates)

    assert result.insurance_income == D("1000.00")
    assert result.employee_contributions == D("100.00")   # 5 % от брутните 2000, не от 1000


def test_contribution_that_does_not_reduce_taxable_income() -> None:
    rates = _rates(
        contributions=(
            ContributionRate("EXTRA", "Допълнителна вноска", D("2.00"), D("0.00"),
                             reduces_taxable_income=False, sort_order=1),
        ),
    )
    result = calculate(ContractInput(base_salary=D("1000.00")), PeriodInput(working_days=20), rates)

    assert result.employee_contributions == D("20.00")
    assert result.taxable_income == D("1000.00")   # вноската не намалява основата
    assert result.income_tax == D("100.00")
    assert result.net_amount == D("880.00")


def test_without_contributions_only_tax_is_withheld() -> None:
    result = calculate(
        ContractInput(base_salary=D("1000.00")),
        PeriodInput(working_days=20),
        RateSet(income_tax_percent=D("10.00")),
    )

    assert result.employee_contributions == D("0.00")
    assert result.employer_contributions == D("0.00")
    assert result.net_amount == D("900.00")


def test_full_month_of_unpaid_leave_yields_nothing() -> None:
    result = calculate(
        ContractInput(base_salary=D("2000.00")),
        PeriodInput(working_days=20, unpaid_leave_days=20),
        _rates(default_min_insurance_income=D("1000.00")),
    )

    assert result.gross_amount == D("0.00")
    assert result.insurance_income == D("0.00")
    assert result.employee_contributions == D("0.00")
    assert result.net_amount == D("0.00")


def test_absences_beyond_working_days_are_rejected() -> None:
    with pytest.raises(ValueError, match="надхвърлят работните дни"):
        calculate(
            ContractInput(base_salary=D("2000.00")),
            PeriodInput(working_days=20, paid_leave_days=15, unpaid_leave_days=10),
            _rates(),
        )


def test_zero_working_days_is_rejected() -> None:
    with pytest.raises(ValueError, match="работни дни"):
        calculate(ContractInput(base_salary=D("2000.00")), PeriodInput(working_days=0), _rates())


def test_negative_salary_is_rejected() -> None:
    with pytest.raises(ValueError, match="отрицателно"):
        calculate(ContractInput(base_salary=D("-1.00")), PeriodInput(working_days=20), _rates())


# ------------------------------------------------------------------ календар
def test_working_days_excludes_weekends_and_holidays() -> None:
    # Май 2026: празници на 1, 6 и 24 май + правилото за преместване при уикенд.
    days = working_days_in_month(2026, 5)
    all_days = [dt.date(2026, 5, d) for d in range(1, 32)]
    weekdays = sum(1 for d in all_days if d.weekday() < 5)
    assert 0 < days < weekdays


def test_january_has_working_days() -> None:
    assert working_days_in_month(2026, 1) >= 20
