"""ДДС модул: кодове, регистри (дневници) и връзка към счетоводството.

Отделен от счетоводното ядро, но интегриран: всеки ДДС запис може да сочи към
счетоводна операция (journal_entry_id). ДДС кодът управлява третирането (виж master
prompt, раздел 6.12): дневник, ставка, право на данъчен кредит, VIES, протокол.

Q-002 / Q-006: точните колони/клетки на официалните ДДС дневници и декларацията, както и
изискванията за самоначисляване/протоколи, подлежат на потвърждение спрямо актуалното
законодателство и техническата спецификация на НАП.
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
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

Money = Numeric(18, 2)
RatePct = Numeric(5, 2)
ZERO = Decimal("0.00")


class VatDirection(str, enum.Enum):
    SALE = "SALE"          # Дневник продажби
    PURCHASE = "PURCHASE"  # Дневник покупки


class VatCode(UUIDMixin, TimestampMixin, Base):
    """ДДС код — управлява данъчното третиране на операцията."""

    __tablename__ = "vat_codes"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_vat_code_company_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[VatDirection] = mapped_column(
        SAEnum(VatDirection, native_enum=False, length=10), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(RatePct, default=ZERO, nullable=False)  # напр. 20.00
    gives_credit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # право на данъчен кредит
    requires_vies: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_protocol: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class VatEntry(UUIDMixin, TimestampMixin, Base):
    """Ред в ДДС регистър (дневник покупки или продажби)."""

    __tablename__ = "vat_entries"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    vat_code_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vat_codes.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[VatDirection] = mapped_column(
        SAEnum(VatDirection, native_enum=False, length=10), nullable=False
    )

    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    tax_event_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_vat_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    tax_base: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)   # данъчна основа
    vat_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)  # начислен ДДС

    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    vat_code: Mapped["VatCode"] = relationship()


class VatPeriodClosing(UUIDMixin, TimestampMixin, Base):
    """Приключване на ДДС период — осчетоводен резултат за периода (VAT Period Closing).

    Затваря ДДС сметките (4531/4532) и осчетоводява резултата към 4538 (за внасяне)
    или 4539 (за възстановяване). След приключване не се допускат нови ДДС записи в
    периода. Един запис на компания+период (уникалност).
    """

    __tablename__ = "vat_period_closings"
    __table_args__ = (
        UniqueConstraint("company_id", "period_id", name="uq_vat_closing_company_period"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    output_vat: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)   # начислен ДДС (4532)
    input_vat: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)    # данъчен кредит (4531)
    net_payable: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)      # ДДС за внасяне
    net_refundable: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)   # ДДС за възстановяване
    closed_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
