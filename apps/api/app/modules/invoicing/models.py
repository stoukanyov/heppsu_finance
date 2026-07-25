"""Фактуриране и вземания — издадени фактури (master prompt 6.10).

При издаване фактура (тип INVOICE) се номерира, осчетоводява (Dr клиенти /
Cr приход + Cr ДДС продажби) и вписва в ДДС дневник продажби. Проформите се
само номерират, без счетоводен и данъчен ефект.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

Money = Numeric(18, 2)
Qty = Numeric(18, 3)
Price = Numeric(18, 4)
ZERO = Decimal("0.00")


class InvoiceType(str, enum.Enum):
    INVOICE = "INVOICE"          # фактура
    PROFORMA = "PROFORMA"        # проформа (без счетоводен/данъчен ефект)
    CREDIT_NOTE = "CREDIT_NOTE"  # кредитно известие
    DEBIT_NOTE = "DEBIT_NOTE"    # дебитно известие
    ADVANCE = "ADVANCE"          # авансова фактура


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"              # чернова
    ISSUED = "ISSUED"           # издадена
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class Invoice(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "series", "number", name="uq_invoice_company_series_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    invoice_type: Mapped[InvoiceType] = mapped_column(
        SAEnum(InvoiceType, native_enum=False, length=15), default=InvoiceType.INVOICE, nullable=False
    )
    series: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # присвоява се при издаване

    issue_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tax_event_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_code_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vat_codes.id", ondelete="RESTRICT"), nullable=True
    )

    subtotal: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)     # данъчна основа
    vat_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus, native_enum=False, length=20), default=InvoiceStatus.DRAFT, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    vat_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vat_entries.id", ondelete="SET NULL"), nullable=True
    )
    # Оригинална фактура при кредитно/дебитно известие.
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.line_no"
    )

    @property
    def full_number(self) -> str | None:
        return f"{self.series}{self.number:010d}" if self.number is not None else None


class InvoiceLine(UUIDMixin, Base):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1.000"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    line_net: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
