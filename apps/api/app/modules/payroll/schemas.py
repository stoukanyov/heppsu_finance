"""Pydantic схеми за модул ТРЗ."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.payroll.models import (
    AbsenceType,
    ContractStatus,
    ContractType,
    ContributionBase,
    PayrollRunStatus,
)

Money = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
Pct = Field(default=Decimal("0.0000"), ge=0, le=100, max_digits=9, decimal_places=4)


# ==================================================================== параметри
class ContributionRateIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=160)
    employee_percent: Decimal = Pct
    employer_percent: Decimal = Pct
    base: ContributionBase = ContributionBase.INSURANCE_INCOME
    reduces_taxable_income: bool = True
    sort_order: int = 0
    gl_expense_account_id: uuid.UUID | None = None
    gl_liability_account_id: uuid.UUID | None = None


class ContributionRateOut(ContributionRateIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class RateSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    valid_from: dt.date
    valid_to: dt.date | None = None
    income_tax_percent: Decimal = Pct
    max_insurance_income: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    default_min_insurance_income: Decimal = Money
    seniority_percent_per_year: Decimal = Pct
    sick_employer_days: int = Field(default=0, ge=0, le=31)
    sick_employer_percent: Decimal = Pct
    notes: str | None = None
    gl_salary_expense_account_id: uuid.UUID | None = None
    gl_salary_payable_account_id: uuid.UUID | None = None
    gl_income_tax_account_id: uuid.UUID | None = None
    contributions: list[ContributionRateIn] = Field(default_factory=list)


class RateSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    income_tax_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=4)
    max_insurance_income: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    default_min_insurance_income: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    seniority_percent_per_year: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=4)
    sick_employer_days: int | None = Field(default=None, ge=0, le=31)
    sick_employer_percent: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=4)
    notes: str | None = None
    gl_salary_expense_account_id: uuid.UUID | None = None
    gl_salary_payable_account_id: uuid.UUID | None = None
    gl_income_tax_account_id: uuid.UUID | None = None
    # Подаден списък заменя изцяло фондовете на набора; None го оставя непроменен.
    contributions: list[ContributionRateIn] | None = None


class RateSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    valid_from: dt.date
    valid_to: dt.date | None
    income_tax_percent: Decimal
    max_insurance_income: Decimal | None
    default_min_insurance_income: Decimal
    seniority_percent_per_year: Decimal
    sick_employer_days: int
    sick_employer_percent: Decimal
    notes: str | None
    gl_salary_expense_account_id: uuid.UUID | None
    gl_salary_payable_account_id: uuid.UUID | None
    gl_income_tax_account_id: uuid.UUID | None
    contributions: list[ContributionRateOut]


# ==================================================================== служители
class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    middle_name: str | None = Field(default=None, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    national_id: str = Field(min_length=1, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    iban: str | None = Field(default=None, max_length=34)
    notes: str | None = None


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    middle_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=255)
    iban: str | None = Field(default=None, max_length=34)
    is_active: bool | None = None
    notes: str | None = None


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    middle_name: str | None
    last_name: str
    full_name: str
    national_id: str
    email: str | None
    phone: str | None
    address: str | None
    iban: str | None
    is_active: bool
    notes: str | None


# ==================================================================== договори
class ContractCreate(BaseModel):
    employee_id: uuid.UUID
    number: str = Field(min_length=1, max_length=50)
    contract_type: ContractType = ContractType.PERMANENT
    position: str = Field(min_length=1, max_length=160)
    nkpd_code: str | None = Field(default=None, max_length=20)
    start_date: dt.date
    end_date: dt.date | None = None
    base_salary: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    hours_per_day: Decimal = Field(default=Decimal("8.00"), gt=0, le=24, max_digits=5, decimal_places=2)
    seniority_years_at_start: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=6, decimal_places=2)
    min_insurance_income: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    paid_leave_days_per_year: int = Field(default=0, ge=0, le=365)


class ContractUpdate(BaseModel):
    position: str | None = Field(default=None, min_length=1, max_length=160)
    nkpd_code: str | None = Field(default=None, max_length=20)
    end_date: dt.date | None = None
    base_salary: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    hours_per_day: Decimal | None = Field(default=None, gt=0, le=24, max_digits=5, decimal_places=2)
    seniority_years_at_start: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    min_insurance_income: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    paid_leave_days_per_year: int | None = Field(default=None, ge=0, le=365)


class ContractTerminate(BaseModel):
    termination_date: dt.date


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    number: str
    contract_type: ContractType
    position: str
    nkpd_code: str | None
    start_date: dt.date
    end_date: dt.date | None
    termination_date: dt.date | None
    base_salary: Decimal
    hours_per_day: Decimal
    seniority_years_at_start: Decimal
    min_insurance_income: Decimal | None
    paid_leave_days_per_year: int
    status: ContractStatus


# ==================================================================== отсъствия
class AbsenceCreate(BaseModel):
    contract_id: uuid.UUID
    absence_type: AbsenceType
    date_from: dt.date
    date_to: dt.date
    note: str | None = Field(default=None, max_length=255)


class AbsenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    absence_type: AbsenceType
    date_from: dt.date
    date_to: dt.date
    note: str | None


# ==================================================================== ведомост
class PayrollRunRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class LineContributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    base_amount: Decimal
    employee_amount: Decimal
    employer_amount: Decimal


class PayrollLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    national_id: str
    position: str
    working_days: int
    worked_days: int
    paid_leave_days: int
    unpaid_leave_days: int
    sick_employer_days: int
    sick_fund_days: int
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
    contributions: list[LineContributionOut]


class PayrollRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    month: int
    status: PayrollRunStatus
    working_days: int
    rate_set_id: uuid.UUID | None
    total_gross: Decimal
    total_employee_contributions: Decimal
    total_employer_contributions: Decimal
    total_income_tax: Decimal
    total_net: Decimal
    journal_entry_id: uuid.UUID | None
    lines: list[PayrollLineOut]


class PayrollRunSummary(BaseModel):
    """Кратък ред за списъка с ведомости (без редовете по служители)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    month: int
    status: PayrollRunStatus
    total_gross: Decimal
    total_net: Decimal
    journal_entry_id: uuid.UUID | None
