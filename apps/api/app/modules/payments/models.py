"""Платежни предложения с maker-checker (master prompt 6.18).

ВАЖНО (сигурност): системата НЕ извършва реални плащания. Тя само подготвя платежни
предложения, маркира рискове и записва одобренията. Един потребител подготвя, друг одобрява
(segregation of duties) — никой не може да одобри собственото си предложение.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

Money = Numeric(18, 2)


class PaymentStatus(str, enum.Enum):
    PREPARED = "PREPARED"      # подготвено (чака одобрение)
    APPROVED = "APPROVED"      # одобрено
    REJECTED = "REJECTED"      # отхвърлено
    CANCELLED = "CANCELLED"    # отменено


class PaymentProposal(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payment_proposals"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_iban: Mapped[str | None] = mapped_column(String(34), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)  # основание
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=20), default=PaymentStatus.PREPARED, nullable=False
    )
    # Рискови маркери, изчислени при подготовката (напр. променен IBAN, висока стойност).
    risk_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    prepared_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
