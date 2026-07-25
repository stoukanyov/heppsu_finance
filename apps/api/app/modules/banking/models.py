"""Банков модул: сметки, движения и съгласуване (master prompt 6.13)."""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
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
ZERO = Decimal("0.00")


class BankTxStatus(str, enum.Enum):
    UNMATCHED = "UNMATCHED"                 # несъпоставено
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"  # частично съпоставено
    MATCHED = "MATCHED"                     # съпоставено
    IGNORED = "IGNORED"                     # игнорирано (напр. вътрешен трансфер)


class BankAccount(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bank_accounts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(34), index=True, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    # Счетоводна сметка, представляваща тази банка (напр. 503) — по избор.
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BankTransaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bank_transactions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bank_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    booking_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    value_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # Знаково: положително = постъпление, отрицателно = плащане.
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Ключ за дедупликация (external_id или хеш) — уникален в рамките на сметката.
    dedup_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[BankTxStatus] = mapped_column(
        SAEnum(BankTxStatus, native_enum=False, length=20), default=BankTxStatus.UNMATCHED, nullable=False
    )

    matches: Mapped[list[BankTransactionMatch]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    @property
    def matched_amount(self) -> Decimal:
        return sum((m.amount for m in self.matches), ZERO)


class BankTransactionMatch(UUIDMixin, TimestampMixin, Base):
    """Съпоставяне на банково движение със счетоводна операция (частично допустимо)."""

    __tablename__ = "bank_transaction_matches"

    bank_transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("bank_transactions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"), nullable=False)
    auto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    transaction: Mapped[BankTransaction] = relationship(back_populates="matches")
