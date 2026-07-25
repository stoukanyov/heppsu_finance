"""Счетоводно ядро: сметкоплан, периоди, двустранни счетоводни операции.

Ключови инварианти (виж master prompt, раздел 6.1):
- Всяка операция е балансирана: общ дебит = общ кредит (в транзакционна и в базова валута).
- Не се осчетоводява по обобщаваща (група) сметка.
- Осчетоводен запис не се редактира и не се изтрива — корекция само чрез сторно.
- Всяка корекция пази връзка към първоначалния запис.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

# Парични типове: суми с 2 знака, валутни курсове с 6 знака.
Money = Numeric(18, 2)
Rate = Numeric(18, 6)
ZERO = Decimal("0.00")


class AccountType(str, enum.Enum):
    ASSET = "ASSET"            # Активи
    LIABILITY = "LIABILITY"    # Пасиви
    EQUITY = "EQUITY"          # Собствен капитал
    REVENUE = "REVENUE"        # Приходи
    EXPENSE = "EXPENSE"        # Разходи
    OFF_BALANCE = "OFF_BALANCE"  # Задбалансови


class JournalType(str, enum.Enum):
    GENERAL = "GENERAL"        # Общ дневник
    SALES = "SALES"            # Продажби
    PURCHASES = "PURCHASES"    # Покупки
    CASH = "CASH"              # Каса
    BANK = "BANK"              # Банка
    FIXED_ASSETS = "FIXED_ASSETS"
    DEPRECIATION = "DEPRECIATION"
    FX = "FX"                  # Валутни операции
    PAYROLL = "PAYROLL"
    CLOSING = "CLOSING"        # Приключвателни
    OPENING = "OPENING"        # Начални салда


class PeriodStatus(str, enum.Enum):
    OPEN = "OPEN"              # Отворен — разрешено осчетоводяване
    RESTRICTED = "RESTRICTED"  # Ограничен — само упълномощени роли
    CLOSING = "CLOSING"        # В процес на приключване
    CLOSED = "CLOSED"          # Приключен
    LOCKED = "LOCKED"          # Окончателно заключен


class EntryStatus(str, enum.Enum):
    DRAFT = "DRAFT"            # Чернова — може да се редактира
    POSTED = "POSTED"          # Осчетоводен — непроменим
    REVERSED = "REVERSED"      # Сторниран (има свързан сторно запис)
    REVERSAL = "REVERSAL"      # Самият сторно запис


class Account(UUIDMixin, TimestampMixin, Base):
    """Счетоводна сметка от индивидуалния сметкоплан на компанията."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_account_company_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AccountType] = mapped_column(SAEnum(AccountType, native_enum=False, length=20), nullable=False)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    # Обобщаваща (синтетична) сметка — забранени директни записи.
    is_group: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Валута за валутни сметки (None = само в базова валута).
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    parent: Mapped["Account | None"] = relationship(remote_side="Account.id", backref="children")


class FiscalYear(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "fiscal_years"
    __table_args__ = (UniqueConstraint("company_id", "year", name="uq_fiscal_year_company_year"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    periods: Mapped[list["AccountingPeriod"]] = relationship(
        back_populates="fiscal_year", cascade="all, delete-orphan"
    )


class AccountingPeriod(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "accounting_periods"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_period_company_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("fiscal_years.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # напр. "2026-07"
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[PeriodStatus] = mapped_column(
        SAEnum(PeriodStatus, native_enum=False, length=20), default=PeriodStatus.OPEN, nullable=False
    )

    fiscal_year: Mapped["FiscalYear"] = relationship(back_populates="periods")


class JournalEntry(UUIDMixin, TimestampMixin, Base):
    """Заглавна част на счетоводна операция (статия)."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "entry_number", name="uq_entry_company_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # Пореден номер в рамките на компанията — присвоява се при осчетоводяване.
    entry_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    journal: Mapped[JournalType] = mapped_column(
        SAEnum(JournalType, native_enum=False, length=20), default=JournalType.GENERAL, nullable=False
    )
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    document_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tax_event_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    posting_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("1.000000"), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[EntryStatus] = mapped_column(
        SAEnum(EntryStatus, native_enum=False, length=20), default=EntryStatus.DRAFT, nullable=False
    )

    # Връзка при сторно: сторно записът сочи към първоначалния.
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    posted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="JournalLine.line_no",
    )
    reverses: Mapped["JournalEntry | None"] = relationship(remote_side="JournalEntry.id")

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit for line in self.lines), ZERO)

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit for line in self.lines), ZERO)


class JournalLine(UUIDMixin, Base):
    """Ред от счетоводна операция. Точно едно от дебит/кредит е > 0."""

    __tablename__ = "journal_lines"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    # Суми в транзакционната валута на операцията.
    debit: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    # Същите суми, преизчислени в базовата валута по курса на операцията.
    debit_base: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    credit_base: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    entry: Mapped["JournalEntry"] = relationship(back_populates="lines")
    account: Mapped["Account"] = relationship()
