"""Регистър на контрагенти (клиенти и доставчици) — master prompt раздел 6.7."""
from __future__ import annotations

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class CounterpartyType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"    # Клиент
    SUPPLIER = "SUPPLIER"    # Доставчик
    BOTH = "BOTH"            # И двете


class Counterparty(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "counterparties"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[CounterpartyType] = mapped_column(
        SAEnum(CounterpartyType, native_enum=False, length=10), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    eik: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="BG", nullable=False)

    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    preferred_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Стандартни счетоводни настройки (по избор).
    default_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    default_vat_code_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("vat_codes.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bank_accounts: Mapped[list[CounterpartyBankAccount]] = relationship(
        back_populates="counterparty", cascade="all, delete-orphan"
    )


class CounterpartyBankAccount(UUIDMixin, Base):
    __tablename__ = "counterparty_bank_accounts"

    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="CASCADE"), index=True, nullable=False
    )
    iban: Mapped[str] = mapped_column(String(34), index=True, nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    counterparty: Mapped[Counterparty] = relationship(back_populates="bank_accounts")
