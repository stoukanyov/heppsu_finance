"""Дълготрайни активи и амортизации (master prompt 6.15).

Амортизацията се предлага от системата и се осчетоводява при човешко действие
(Dr разход за амортизация / Cr натрупана амортизация). За MVP — линеен метод.
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
ZERO = Decimal("0.00")


class AssetStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"          # в експлоатация
    DISPOSED = "DISPOSED"      # продаден
    WRITTEN_OFF = "WRITTEN_OFF"  # бракуван


class DepreciationMethod(str, enum.Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"  # линеен


class FixedAsset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "fixed_assets"
    __table_args__ = (
        UniqueConstraint("company_id", "inventory_number", name="uq_asset_company_invno"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    inventory_number: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    acquisition_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    in_service_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    initial_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[DepreciationMethod] = mapped_column(
        SAEnum(DepreciationMethod, native_enum=False, length=20),
        default=DepreciationMethod.STRAIGHT_LINE,
        nullable=False,
    )
    accumulated_depreciation: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    responsible_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[AssetStatus] = mapped_column(
        SAEnum(AssetStatus, native_enum=False, length=20), default=AssetStatus.ACTIVE, nullable=False
    )
    disposal_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # Счетоводни сметки за амортизация (напр. 603 / 241) — нужни за осчетоводяване.
    gl_asset_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    gl_expense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    gl_accum_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    depreciations: Mapped[list[DepreciationEntry]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def depreciable_base(self) -> Decimal:
        return self.initial_cost - self.residual_value

    @property
    def net_book_value(self) -> Decimal:
        return self.initial_cost - self.accumulated_depreciation


class DepreciationEntry(UUIDMixin, TimestampMixin, Base):
    """Осчетоводена месечна амортизация за актив (уникална за актив+месец)."""

    __tablename__ = "depreciation_entries"
    __table_args__ = (
        UniqueConstraint("asset_id", "year", "month", name="uq_depr_asset_period"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("fixed_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    asset: Mapped[FixedAsset] = relationship(back_populates="depreciations")
