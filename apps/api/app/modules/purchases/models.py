"""Получени фактури от доставчици (AP) — master prompt 6.9/6.11.

При осчетоводяване: Dr разход (+ Dr ДДС покупки при право на кредит) / Cr доставчик,
и вписване в ДДС дневник покупки. Номерът е на доставчика (не наша серия).
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


class PurchaseStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CANCELLED = "CANCELLED"


class PurchaseInvoice(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "purchase_invoices"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    supplier_document_number: Mapped[str] = mapped_column(String(50), nullable=False)

    document_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tax_event_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_code_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vat_codes.id", ondelete="RESTRICT"), nullable=True
    )
    # Разходна сметка за дебитиране (напр. 602). По избор — по подразбиране 602.
    expense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    subtotal: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    status: Mapped[PurchaseStatus] = mapped_column(
        SAEnum(PurchaseStatus, native_enum=False, length=20), default=PurchaseStatus.DRAFT, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    vat_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vat_entries.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    lines: Mapped[list[PurchaseInvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="PurchaseInvoiceLine.line_no"
    )


class PurchaseInvoiceLine(UUIDMixin, Base):
    __tablename__ = "purchase_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_invoices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1.000"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    line_net: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")
