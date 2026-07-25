"""ТРЗ — служители, трудови договори, параметри на осигуряването и ведомости.

Ключово решение (D-011): **никоя ставка, процент или праг не е в кода.** Всичко живее в
`PayrollRateSet` + `PayrollContributionRate` и се въвежда през UI. Наборът е версиониран по
период (`valid_from`/`valid_to`), защото осигурителните проценти и праговете се сменят
всяка година — смяната на година е нов ред в базата, не ново издание на софтуера.

Изчислението е в `calc.py` (чисто, без БД). Тук са само данните.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

Money = Numeric(18, 2)
# Процентите се пазят като процент (10.00 = 10 %), не като дроб — така полето в UI
# показва точно това, което счетоводителят чете в нормативния текст.
Percent = Numeric(9, 4)
ZERO = Decimal("0.00")


# ==================================================================== номенклатури
class ContractType(str, enum.Enum):
    PERMANENT = "PERMANENT"        # безсрочен трудов договор
    FIXED_TERM = "FIXED_TERM"      # срочен трудов договор
    ADDITIONAL = "ADDITIONAL"      # допълнителен трудов договор
    MANAGEMENT = "MANAGEMENT"      # договор за управление и контрол


class ContractStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ContributionBase(str, enum.Enum):
    """Върху какво се начислява вноската."""

    INSURANCE_INCOME = "INSURANCE_INCOME"  # осигурителен доход (с прилагане на праговете)
    GROSS = "GROSS"                        # брутно възнаграждение, без прагове


class AbsenceType(str, enum.Enum):
    PAID_LEAVE = "PAID_LEAVE"        # платен годишен отпуск
    UNPAID_LEAVE = "UNPAID_LEAVE"    # неплатен отпуск
    SICK_EMPLOYER = "SICK_EMPLOYER"  # болничен за сметка на работодателя
    SICK_FUND = "SICK_FUND"          # болничен за сметка на осигурителя (НОИ)


class PayrollRunStatus(str, enum.Enum):
    DRAFT = "DRAFT"              # чернова
    CALCULATED = "CALCULATED"    # изчислена
    APPROVED = "APPROVED"        # одобрена
    POSTED = "POSTED"            # осчетоводена
    CANCELLED = "CANCELLED"      # сторнирана


# ==================================================================== параметри
class PayrollRateSet(UUIDMixin, TimestampMixin, Base):
    """Набор осигурителни и данъчни параметри, валиден за период.

    Въвежда се изцяло през UI. Ведомостта пази кой набор е ползвала, за да може
    една стара ведомост да се преизчисли със ставките, които са били в сила тогава.
    """

    __tablename__ = "payroll_rate_sets"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    income_tax_percent: Mapped[Decimal] = mapped_column(Percent, default=ZERO, nullable=False)
    max_insurance_income: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    default_min_insurance_income: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    # Клас „прослужено време“ — процент върху основното възнаграждение за всяка година стаж.
    seniority_percent_per_year: Mapped[Decimal] = mapped_column(Percent, default=ZERO, nullable=False)
    # Първите N работни дни от болничен са за сметка на работодателя, платени с този процент.
    sick_employer_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_employer_percent: Mapped[Decimal] = mapped_column(Percent, default=ZERO, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Сметки за осчетоводяване на ведомостта — също параметър, не константа в кода.
    gl_salary_expense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    gl_salary_payable_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    gl_income_tax_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    contributions: Mapped[list[PayrollContributionRate]] = relationship(
        back_populates="rate_set", cascade="all, delete-orphan", order_by="PayrollContributionRate.sort_order"
    )


class PayrollContributionRate(UUIDMixin, TimestampMixin, Base):
    """Един осигурителен фонд с процентите за двете страни.

    Фондовете НЕ са изброени в кода — потребителят добавя толкова редове, колкото са
    му нужни (ДОО, ДЗПО, здравно, ТЗПБ, …), с имената и процентите, които са в сила.
    """

    __tablename__ = "payroll_contribution_rates"
    __table_args__ = (
        UniqueConstraint("rate_set_id", "code", name="uq_payroll_contrib_code"),
    )

    rate_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_rate_sets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    employee_percent: Mapped[Decimal] = mapped_column(Percent, default=ZERO, nullable=False)
    employer_percent: Mapped[Decimal] = mapped_column(Percent, default=ZERO, nullable=False)
    base: Mapped[ContributionBase] = mapped_column(
        SAEnum(ContributionBase, native_enum=False, length=20),
        default=ContributionBase.INSURANCE_INCOME,
        nullable=False,
    )
    # Приспада ли се вноската от облагаемия доход за ДОД (вноските на лицето — да).
    reduces_taxable_income: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Счетоводни сметки за осчетоводяване на вноската (разход и разчет).
    gl_expense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    gl_liability_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    rate_set: Mapped[PayrollRateSet] = relationship(back_populates="contributions")


# ==================================================================== хора
class Employee(UUIDMixin, TimestampMixin, Base):
    """Служител (физическо лице). Идентифицира се уникално по ЕГН/ЛНЧ в рамките на фирмата."""

    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("company_id", "national_id", name="uq_employee_company_national_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    national_id: Mapped[str] = mapped_column(String(20), nullable=False)  # ЕГН / ЛНЧ

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    contracts: Mapped[list[EmploymentContract]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)


class EmploymentContract(UUIDMixin, TimestampMixin, Base):
    """Трудов договор — носи възнаграждението и осигурителните особености."""

    __tablename__ = "employment_contracts"
    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_contract_company_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    contract_type: Mapped[ContractType] = mapped_column(
        SAEnum(ContractType, native_enum=False, length=20), default=ContractType.PERMANENT, nullable=False
    )
    position: Mapped[str] = mapped_column(String(160), nullable=False)       # длъжност
    nkpd_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # код по НКПД

    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)          # за срочните
    termination_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # реално прекратяване

    base_salary: Mapped[Decimal] = mapped_column(Money, nullable=False)
    hours_per_day: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("8.00"), nullable=False)
    # Признат стаж към датата на сключване — базата за класа „прослужено време“.
    seniority_years_at_start: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=ZERO, nullable=False)
    # Индивидуален минимален осигурителен праг (по НКПД/дейност); празно = по подразбиране от набора.
    min_insurance_income: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    paid_leave_days_per_year: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus, native_enum=False, length=20), default=ContractStatus.ACTIVE, nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="contracts")


class Absence(UUIDMixin, TimestampMixin, Base):
    """Отсъствие по договор — отпуск или болничен, в работни дни."""

    __tablename__ = "payroll_absences"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employment_contracts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    absence_type: Mapped[AbsenceType] = mapped_column(
        SAEnum(AbsenceType, native_enum=False, length=20), nullable=False
    )
    date_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    date_to: Mapped[dt.date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ==================================================================== ведомост
class PayrollRun(UUIDMixin, TimestampMixin, Base):
    """Ведомост за един месец."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "year", "month", name="uq_payroll_run_period"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_set_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payroll_rate_sets.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[PayrollRunStatus] = mapped_column(
        SAEnum(PayrollRunStatus, native_enum=False, length=20),
        default=PayrollRunStatus.DRAFT,
        nullable=False,
    )
    working_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    total_gross: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total_employee_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total_employer_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total_income_tax: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total_net: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list[PayrollLine]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PayrollLine(UUIDMixin, TimestampMixin, Base):
    """Ред от ведомостта — един договор за един месец.

    Имената и длъжността се пазят като снимка към момента на изчисление: ведомостта е
    документ и не бива да се променя, ако служителят по-късно смени длъжност.
    """

    __tablename__ = "payroll_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "contract_id", name="uq_payroll_line_run_contract"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employment_contracts.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    national_id: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[str] = mapped_column(String(160), nullable=False)

    working_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worked_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paid_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unpaid_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_employer_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_fund_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    base_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    seniority_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    additional_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    sick_employer_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    insurance_income: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    employee_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    employer_contributions: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    taxable_income: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    tax_relief: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    income_tax: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    other_deductions: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    run: Mapped[PayrollRun] = relationship(back_populates="lines")
    contributions: Mapped[list[PayrollLineContribution]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="PayrollLineContribution.sort_order"
    )


class PayrollLineContribution(UUIDMixin, Base):
    """Разбивка по фондове за един ред — основата за декларация обр. 1."""

    __tablename__ = "payroll_line_contributions"

    line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_lines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    employee_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    employer_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    line: Mapped[PayrollLine] = relationship(back_populates="contributions")
