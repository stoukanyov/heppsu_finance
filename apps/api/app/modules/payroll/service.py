"""Бизнес логика на ТРЗ: параметри, служители, договори, отсъствия и ведомост.

Слоят само оркестрира — самото изчисление живее в `calc.py` и не знае за базата.
"""
from __future__ import annotations

import calendar
import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.modules.accounting.models import Account, JournalType
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, post_entry
from app.modules.companies.models import Company
from app.modules.deadlines.holidays import is_working_day
from app.modules.payroll import calc
from app.modules.payroll.models import (
    ZERO,
    Absence,
    AbsenceType,
    ContractStatus,
    ContributionBase,
    Employee,
    EmploymentContract,
    PayrollContributionRate,
    PayrollLine,
    PayrollLineContribution,
    PayrollRateSet,
    PayrollRun,
    PayrollRunStatus,
)
from app.modules.payroll.schemas import (
    AbsenceCreate,
    ContractCreate,
    ContractUpdate,
    ContributionRateIn,
    EmployeeCreate,
    EmployeeUpdate,
    RateSetCreate,
    RateSetUpdate,
)

_MONTHS = (
    "януари", "февруари", "март", "април", "май", "юни",
    "юли", "август", "септември", "октомври", "ноември", "декември",
)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def _validate_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.company_id != company_id:
        raise _err("Сметката не съществува в тази компания")
    if account.is_group:
        raise _err(f"Сметка {account.code} е обобщаваща — избери аналитична")
    return account


# ==================================================================== параметри
def _apply_contributions(
    db: Session, company_id: uuid.UUID, rate_set: PayrollRateSet, rows: list[ContributionRateIn]
) -> None:
    codes = [row.code for row in rows]
    if len(set(codes)) != len(codes):
        raise _err("Кодовете на фондовете в един набор трябва да са уникални")
    rate_set.contributions.clear()
    for row in rows:
        for field_name in ("gl_expense_account_id", "gl_liability_account_id"):
            acc_id = getattr(row, field_name)
            if acc_id is not None:
                _validate_account(db, company_id, acc_id)
        rate_set.contributions.append(
            PayrollContributionRate(
                code=row.code,
                name=row.name,
                employee_percent=row.employee_percent,
                employer_percent=row.employer_percent,
                base=row.base,
                reduces_taxable_income=row.reduces_taxable_income,
                sort_order=row.sort_order,
                gl_expense_account_id=row.gl_expense_account_id,
                gl_liability_account_id=row.gl_liability_account_id,
            )
        )


def _validate_rate_set_accounts(db: Session, company_id: uuid.UUID, data) -> None:
    for field_name in (
        "gl_salary_expense_account_id",
        "gl_salary_payable_account_id",
        "gl_income_tax_account_id",
    ):
        acc_id = getattr(data, field_name, None)
        if acc_id is not None:
            _validate_account(db, company_id, acc_id)


def create_rate_set(db: Session, company_id: uuid.UUID, data: RateSetCreate) -> PayrollRateSet:
    if data.valid_to is not None and data.valid_to < data.valid_from:
        raise _err("Краят на периода не може да е преди началото")
    _validate_rate_set_accounts(db, company_id, data)

    payload = data.model_dump(exclude={"contributions"})
    rate_set = PayrollRateSet(company_id=company_id, **payload)
    _apply_contributions(db, company_id, rate_set, data.contributions)
    db.add(rate_set)
    db.commit()
    db.refresh(rate_set)
    return rate_set


def list_rate_sets(db: Session, company_id: uuid.UUID) -> list[PayrollRateSet]:
    return list(
        db.scalars(
            select(PayrollRateSet)
            .options(selectinload(PayrollRateSet.contributions))
            .where(PayrollRateSet.company_id == company_id)
            .order_by(PayrollRateSet.valid_from.desc())
        )
    )


def get_rate_set(db: Session, company_id: uuid.UUID, rate_set_id: uuid.UUID) -> PayrollRateSet:
    rate_set = db.get(PayrollRateSet, rate_set_id)
    if rate_set is None or rate_set.company_id != company_id:
        raise _err("Наборът параметри не е намерен", status.HTTP_404_NOT_FOUND)
    return rate_set


def update_rate_set(
    db: Session, company_id: uuid.UUID, rate_set_id: uuid.UUID, data: RateSetUpdate
) -> PayrollRateSet:
    rate_set = get_rate_set(db, company_id, rate_set_id)
    if _runs_using(db, rate_set_id, locked_only=True):
        raise _err(
            "Наборът е ползван от одобрена или осчетоводена ведомост и не може да се променя. "
            "Създай нов набор с нов период на валидност.",
            status.HTTP_409_CONFLICT,
        )
    _validate_rate_set_accounts(db, company_id, data)

    payload = data.model_dump(exclude={"contributions"}, exclude_unset=True)
    for key, value in payload.items():
        setattr(rate_set, key, value)
    if rate_set.valid_to is not None and rate_set.valid_to < rate_set.valid_from:
        raise _err("Краят на периода не може да е преди началото")
    if data.contributions is not None:
        _apply_contributions(db, company_id, rate_set, data.contributions)

    db.commit()
    db.refresh(rate_set)
    return rate_set


def delete_rate_set(db: Session, company_id: uuid.UUID, rate_set_id: uuid.UUID) -> None:
    rate_set = get_rate_set(db, company_id, rate_set_id)
    if _runs_using(db, rate_set_id):
        raise _err("Наборът е ползван от ведомост и не може да се изтрие", status.HTTP_409_CONFLICT)
    db.delete(rate_set)
    db.commit()


def _runs_using(db: Session, rate_set_id: uuid.UUID, locked_only: bool = False) -> bool:
    stmt = select(PayrollRun.id).where(PayrollRun.rate_set_id == rate_set_id)
    if locked_only:
        stmt = stmt.where(
            PayrollRun.status.in_((PayrollRunStatus.APPROVED, PayrollRunStatus.POSTED))
        )
    return db.scalar(stmt.limit(1)) is not None


def resolve_rate_set(db: Session, company_id: uuid.UUID, on_date: dt.date) -> PayrollRateSet:
    """Наборът, валиден към дадена дата. Липсата му е ясна грешка, не мълчаливо нула."""
    rate_set = db.scalar(
        select(PayrollRateSet)
        .options(selectinload(PayrollRateSet.contributions))
        .where(
            PayrollRateSet.company_id == company_id,
            PayrollRateSet.valid_from <= on_date,
            (PayrollRateSet.valid_to.is_(None)) | (PayrollRateSet.valid_to >= on_date),
        )
        .order_by(PayrollRateSet.valid_from.desc())
        .limit(1)
    )
    if rate_set is None:
        raise _err(
            f"Няма набор осигурителни параметри, валиден към {on_date:%d.%m.%Y}. "
            "Създай го в „ТРЗ → Параметри“.",
            status.HTTP_409_CONFLICT,
        )
    return rate_set


def to_calc_rates(rate_set: PayrollRateSet) -> calc.RateSet:
    """Превръща записа от базата във входа на чистото изчисление."""
    return calc.RateSet(
        income_tax_percent=rate_set.income_tax_percent,
        max_insurance_income=rate_set.max_insurance_income,
        default_min_insurance_income=rate_set.default_min_insurance_income,
        seniority_percent_per_year=rate_set.seniority_percent_per_year,
        sick_employer_days=rate_set.sick_employer_days,
        sick_employer_percent=rate_set.sick_employer_percent,
        contributions=tuple(
            calc.ContributionRate(
                code=c.code,
                name=c.name,
                employee_percent=c.employee_percent,
                employer_percent=c.employer_percent,
                on_insurance_income=c.base == ContributionBase.INSURANCE_INCOME,
                reduces_taxable_income=c.reduces_taxable_income,
                sort_order=c.sort_order,
            )
            for c in rate_set.contributions
        ),
    )


# ==================================================================== служители
def create_employee(db: Session, company_id: uuid.UUID, data: EmployeeCreate) -> Employee:
    employee = Employee(company_id=company_id, **data.model_dump())
    db.add(employee)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(
            f"Служител с ЕГН/ЛНЧ {data.national_id} вече съществува", status.HTTP_409_CONFLICT
        )
    db.refresh(employee)
    return employee


def list_employees(db: Session, company_id: uuid.UUID, active_only: bool = False) -> list[Employee]:
    stmt = select(Employee).where(Employee.company_id == company_id)
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    return list(db.scalars(stmt.order_by(Employee.last_name, Employee.first_name)))


def get_employee(db: Session, company_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None or employee.company_id != company_id:
        raise _err("Служителят не е намерен", status.HTTP_404_NOT_FOUND)
    return employee


def update_employee(
    db: Session, company_id: uuid.UUID, employee_id: uuid.UUID, data: EmployeeUpdate
) -> Employee:
    employee = get_employee(db, company_id, employee_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(employee, key, value)
    db.commit()
    db.refresh(employee)
    return employee


# ==================================================================== договори
def create_contract(
    db: Session, company_id: uuid.UUID, data: ContractCreate
) -> EmploymentContract:
    get_employee(db, company_id, data.employee_id)   # проверява и тенанта
    if data.end_date is not None and data.end_date < data.start_date:
        raise _err("Краят на договора не може да е преди началото")

    contract = EmploymentContract(company_id=company_id, **data.model_dump())
    db.add(contract)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(f"Договор с номер {data.number} вече съществува", status.HTTP_409_CONFLICT)
    db.refresh(contract)
    return contract


def list_contracts(
    db: Session, company_id: uuid.UUID, employee_id: uuid.UUID | None = None
) -> list[EmploymentContract]:
    stmt = select(EmploymentContract).where(EmploymentContract.company_id == company_id)
    if employee_id is not None:
        stmt = stmt.where(EmploymentContract.employee_id == employee_id)
    return list(db.scalars(stmt.order_by(EmploymentContract.start_date.desc())))


def get_contract(
    db: Session, company_id: uuid.UUID, contract_id: uuid.UUID
) -> EmploymentContract:
    contract = db.get(EmploymentContract, contract_id)
    if contract is None or contract.company_id != company_id:
        raise _err("Договорът не е намерен", status.HTTP_404_NOT_FOUND)
    return contract


def update_contract(
    db: Session, company_id: uuid.UUID, contract_id: uuid.UUID, data: ContractUpdate
) -> EmploymentContract:
    contract = get_contract(db, company_id, contract_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(contract, key, value)
    db.commit()
    db.refresh(contract)
    return contract


def terminate_contract(
    db: Session, company_id: uuid.UUID, contract_id: uuid.UUID, on_date: dt.date
) -> EmploymentContract:
    contract = get_contract(db, company_id, contract_id)
    if contract.status == ContractStatus.TERMINATED:
        raise _err("Договорът вече е прекратен", status.HTTP_409_CONFLICT)
    if on_date < contract.start_date:
        raise _err("Датата на прекратяване не може да е преди началото на договора")
    contract.termination_date = on_date
    contract.status = ContractStatus.TERMINATED
    db.commit()
    db.refresh(contract)
    return contract


# ==================================================================== отсъствия
def create_absence(db: Session, company_id: uuid.UUID, data: AbsenceCreate) -> Absence:
    get_contract(db, company_id, data.contract_id)
    if data.date_to < data.date_from:
        raise _err("Краят на отсъствието не може да е преди началото")
    absence = Absence(company_id=company_id, **data.model_dump())
    db.add(absence)
    db.commit()
    db.refresh(absence)
    return absence


def list_absences(
    db: Session,
    company_id: uuid.UUID,
    contract_id: uuid.UUID | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[Absence]:
    stmt = select(Absence).where(Absence.company_id == company_id)
    if contract_id is not None:
        stmt = stmt.where(Absence.contract_id == contract_id)
    if date_from is not None:
        stmt = stmt.where(Absence.date_to >= date_from)
    if date_to is not None:
        stmt = stmt.where(Absence.date_from <= date_to)
    return list(db.scalars(stmt.order_by(Absence.date_from.desc())))


def delete_absence(db: Session, company_id: uuid.UUID, absence_id: uuid.UUID) -> None:
    absence = db.get(Absence, absence_id)
    if absence is None or absence.company_id != company_id:
        raise _err("Отсъствието не е намерено", status.HTTP_404_NOT_FOUND)
    db.delete(absence)
    db.commit()


def _working_days_between(start: dt.date, end: dt.date) -> int:
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if is_working_day(current):
            days += 1
        current += dt.timedelta(days=1)
    return days


# ==================================================================== ведомост
def _active_contracts(
    db: Session, company_id: uuid.UUID, month_start: dt.date, month_end: dt.date
) -> list[EmploymentContract]:
    """Договорите, действали поне един ден през месеца."""
    stmt = (
        select(EmploymentContract)
        .options(selectinload(EmploymentContract.employee))
        .where(
            EmploymentContract.company_id == company_id,
            EmploymentContract.start_date <= month_end,
            (EmploymentContract.termination_date.is_(None))
            | (EmploymentContract.termination_date >= month_start),
        )
        .order_by(EmploymentContract.number)
    )
    return list(db.scalars(stmt))


def _absence_days(
    absences: list[Absence], month_start: dt.date, month_end: dt.date
) -> dict[AbsenceType, int]:
    """Работните дни отсъствие по видове, орязани в границите на месеца."""
    days: dict[AbsenceType, int] = {t: 0 for t in AbsenceType}
    for absence in absences:
        start = max(absence.date_from, month_start)
        end = min(absence.date_to, month_end)
        days[absence.absence_type] += _working_days_between(start, end)
    return days


def get_run(db: Session, company_id: uuid.UUID, run_id: uuid.UUID) -> PayrollRun:
    run = db.get(PayrollRun, run_id)
    if run is None or run.company_id != company_id:
        raise _err("Ведомостта не е намерена", status.HTTP_404_NOT_FOUND)
    return run


def list_runs(db: Session, company_id: uuid.UUID) -> list[PayrollRun]:
    return list(
        db.scalars(
            select(PayrollRun)
            .where(PayrollRun.company_id == company_id)
            .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
        )
    )


def _find_run(db: Session, company_id: uuid.UUID, year: int, month: int) -> PayrollRun | None:
    return db.scalar(
        select(PayrollRun).where(
            PayrollRun.company_id == company_id,
            PayrollRun.year == year,
            PayrollRun.month == month,
        )
    )


def calculate_run(db: Session, company_id: uuid.UUID, year: int, month: int) -> PayrollRun:
    """Изчислява (или преизчислява) ведомостта за месеца.

    Одобрената и осчетоводената ведомост не се пипат — те са документ.
    """
    month_start, month_end = _month_bounds(year, month)
    rate_set = resolve_rate_set(db, company_id, month_end)
    working_days = calc.working_days_in_month(year, month)

    run = _find_run(db, company_id, year, month)
    if run is not None and run.status in (PayrollRunStatus.APPROVED, PayrollRunStatus.POSTED):
        raise _err(
            f"Ведомостта за {_MONTHS[month - 1]} {year} е {run.status.value} и не се преизчислява. "
            "Сторнирай я, ако трябва да се промени.",
            status.HTTP_409_CONFLICT,
        )
    if run is None:
        run = PayrollRun(company_id=company_id, year=year, month=month)
        db.add(run)
    else:
        # Изтриването трябва да стигне до базата ПРЕДИ новите редове: в един flush
        # SQLAlchemy подрежда INSERT преди DELETE и уникалният индекс (ведомост+договор)
        # би се задействал при преизчисление.
        run.lines.clear()
        db.flush()

    run.rate_set_id = rate_set.id
    run.working_days = working_days
    rates = to_calc_rates(rate_set)

    totals = dict(gross=ZERO, employee=ZERO, employer=ZERO, tax=ZERO, net=ZERO)
    for contract in _active_contracts(db, company_id, month_start, month_end):
        absences = list_absences(db, company_id, contract.id, month_start, month_end)
        by_type = _absence_days(absences, month_start, month_end)

        # Дните извън срока на договора се третират като неплатени — така частичният
        # месец при постъпване или напускане минава през същата пропорционална логика.
        outside = 0
        if contract.start_date > month_start:
            outside += _working_days_between(month_start, contract.start_date - dt.timedelta(days=1))
        if contract.termination_date is not None and contract.termination_date < month_end:
            outside += _working_days_between(
                contract.termination_date + dt.timedelta(days=1), month_end
            )

        period = calc.PeriodInput(
            working_days=working_days,
            paid_leave_days=by_type[AbsenceType.PAID_LEAVE],
            unpaid_leave_days=by_type[AbsenceType.UNPAID_LEAVE] + outside,
            sick_employer_days=by_type[AbsenceType.SICK_EMPLOYER],
            sick_fund_days=by_type[AbsenceType.SICK_FUND],
        )
        contract_input = calc.ContractInput(
            base_salary=contract.base_salary,
            seniority_years=contract.seniority_years_at_start,
            min_insurance_income=contract.min_insurance_income,
        )
        try:
            result = calc.calculate(contract_input, period, rates)
        except ValueError as exc:
            raise _err(f"Договор {contract.number}: {exc}") from exc

        line = PayrollLine(
            contract_id=contract.id,
            employee_id=contract.employee_id,
            employee_name=contract.employee.full_name,
            national_id=contract.employee.national_id,
            position=contract.position,
            working_days=working_days,
            worked_days=result.worked_days,
            paid_leave_days=period.paid_leave_days,
            unpaid_leave_days=period.unpaid_leave_days,
            sick_employer_days=period.sick_employer_days,
            sick_fund_days=period.sick_fund_days,
            base_amount=result.base_amount,
            seniority_amount=result.seniority_amount,
            additional_amount=result.additional_amount,
            sick_employer_amount=result.sick_employer_amount,
            gross_amount=result.gross_amount,
            insurance_income=result.insurance_income,
            employee_contributions=result.employee_contributions,
            employer_contributions=result.employer_contributions,
            taxable_income=result.taxable_income,
            tax_relief=result.tax_relief,
            income_tax=result.income_tax,
            other_deductions=result.other_deductions,
            net_amount=result.net_amount,
        )
        for item in result.contributions:
            line.contributions.append(
                PayrollLineContribution(
                    code=item.code,
                    name=item.name,
                    base_amount=item.base_amount,
                    employee_amount=item.employee_amount,
                    employer_amount=item.employer_amount,
                    sort_order=item.sort_order,
                )
            )
        run.lines.append(line)

        totals["gross"] += result.gross_amount
        totals["employee"] += result.employee_contributions
        totals["employer"] += result.employer_contributions
        totals["tax"] += result.income_tax
        totals["net"] += result.net_amount

    run.total_gross = totals["gross"]
    run.total_employee_contributions = totals["employee"]
    run.total_employer_contributions = totals["employer"]
    run.total_income_tax = totals["tax"]
    run.total_net = totals["net"]
    run.status = PayrollRunStatus.CALCULATED

    db.commit()
    db.refresh(run)
    return run


def approve_run(
    db: Session, company_id: uuid.UUID, run_id: uuid.UUID, user_id: uuid.UUID
) -> PayrollRun:
    run = get_run(db, company_id, run_id)
    if run.status != PayrollRunStatus.CALCULATED:
        raise _err("Само изчислена ведомост може да се одобри", status.HTTP_409_CONFLICT)
    if not run.lines:
        raise _err("Ведомостта няма редове", status.HTTP_409_CONFLICT)
    run.status = PayrollRunStatus.APPROVED
    run.approved_by_id = user_id
    run.approved_at = dt.datetime.now(dt.UTC)
    db.commit()
    db.refresh(run)
    return run


def _posting_lines(
    db: Session, run: PayrollRun, rate_set: PayrollRateSet
) -> list[JournalLineIn]:
    """Съставя редовете на счетоводната статия за ведомостта.

    Dr Разход за заплати (брутно) + Dr Разход за осигуровки на работодателя
    Cr Персонал (нето) + Cr Данък върху доходите + Cr Разчети по фондове
    """
    missing: list[str] = []
    if rate_set.gl_salary_expense_account_id is None:
        missing.append("сметка за разход за заплати")
    if rate_set.gl_salary_payable_account_id is None:
        missing.append("сметка за разчети с персонала")
    if run.total_income_tax > ZERO and rate_set.gl_income_tax_account_id is None:
        missing.append("сметка за данък върху доходите")

    # Сумите по фондове за цялата ведомост.
    by_code: dict[str, dict[str, Decimal]] = {}
    for line in run.lines:
        for item in line.contributions:
            bucket = by_code.setdefault(item.code, {"employee": ZERO, "employer": ZERO})
            bucket["employee"] += item.employee_amount
            bucket["employer"] += item.employer_amount

    rates_by_code = {c.code: c for c in rate_set.contributions}
    for code, amounts in by_code.items():
        rate = rates_by_code.get(code)
        total = amounts["employee"] + amounts["employer"]
        if total == ZERO:
            continue
        if rate is None or rate.gl_liability_account_id is None:
            missing.append(f"сметка за разчет по фонд „{code}“")
        if amounts["employer"] > ZERO and (rate is None or rate.gl_expense_account_id is None):
            missing.append(f"сметка за разход по фонд „{code}“")

    if missing:
        raise _err(
            "Липсват сметки за осчетоводяване: " + ", ".join(sorted(set(missing)))
            + ". Задай ги в „ТРЗ → Параметри“.",
            status.HTTP_409_CONFLICT,
        )

    lines = [
        JournalLineIn(
            account_id=rate_set.gl_salary_expense_account_id,
            debit=run.total_gross,
            credit=ZERO,
            description="Начислени възнаграждения",
        ),
        JournalLineIn(
            account_id=rate_set.gl_salary_payable_account_id,
            debit=ZERO,
            credit=run.total_net,
            description="Дължими възнаграждения",
        ),
    ]
    if run.total_income_tax > ZERO:
        lines.append(
            JournalLineIn(
                account_id=rate_set.gl_income_tax_account_id,
                debit=ZERO,
                credit=run.total_income_tax,
                description="Данък върху доходите",
            )
        )
    for code in sorted(by_code):
        amounts = by_code[code]
        rate = rates_by_code[code]
        total = amounts["employee"] + amounts["employer"]
        if total == ZERO:
            continue
        if amounts["employer"] > ZERO:
            lines.append(
                JournalLineIn(
                    account_id=rate.gl_expense_account_id,
                    debit=amounts["employer"],
                    credit=ZERO,
                    description=f"Осигуровки за сметка на работодателя — {rate.name}",
                )
            )
        lines.append(
            JournalLineIn(
                account_id=rate.gl_liability_account_id,
                debit=ZERO,
                credit=total,
                description=f"Разчети по {rate.name}",
            )
        )
    return lines


def post_run(
    db: Session, company: Company, run_id: uuid.UUID, user_id: uuid.UUID
) -> PayrollRun:
    run = get_run(db, company.id, run_id)
    if run.status != PayrollRunStatus.APPROVED:
        raise _err("Само одобрена ведомост може да се осчетоводи", status.HTTP_409_CONFLICT)
    if run.rate_set_id is None:
        raise _err("Ведомостта няма набор параметри", status.HTTP_409_CONFLICT)

    rate_set = get_rate_set(db, company.id, run.rate_set_id)
    lines = _posting_lines(db, run, rate_set)
    _, month_end = _month_bounds(run.year, run.month)

    entry_data = JournalEntryCreate(
        document_date=month_end,
        journal=JournalType.PAYROLL,
        document_type="Ведомост",
        document_number=f"TRZ-{run.year}{run.month:02d}",
        description=f"Ведомост за {_MONTHS[run.month - 1]} {run.year}",
        lines=lines,
    )
    entry = create_entry(db, company, user_id, entry_data)
    post_entry(db, company.id, entry.id, user_id)

    run.journal_entry_id = entry.id
    run.status = PayrollRunStatus.POSTED
    db.commit()
    db.refresh(run)
    return run


def cancel_run(db: Session, company_id: uuid.UUID, run_id: uuid.UUID) -> PayrollRun:
    """Връща одобрена ведомост в чернова. Осчетоводената иска сторно на статията."""
    run = get_run(db, company_id, run_id)
    if run.status == PayrollRunStatus.POSTED:
        raise _err(
            "Ведомостта е осчетоводена — сторнирай счетоводната операция, преди да я отказваш",
            status.HTTP_409_CONFLICT,
        )
    if run.status == PayrollRunStatus.CANCELLED:
        raise _err("Ведомостта вече е сторнирана", status.HTTP_409_CONFLICT)
    run.status = PayrollRunStatus.CALCULATED
    run.approved_by_id = None
    run.approved_at = None
    db.commit()
    db.refresh(run)
    return run
