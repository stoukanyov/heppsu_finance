"""Модул „Магазини": продажби от App Store и Google Play.

Нормализира данните от двата магазина в единен модел `StoreSale`, за да могат да се
анализират заедно (кое приложение се продава най-добре, в коя държава, кога). Суровите
данни идват през конектори (виж `connectors/`), които капсулират API-тата на Apple/Google.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

Money = Numeric(18, 2)
ZERO = Decimal("0.00")


class StorePlatform(str, enum.Enum):
    APP_STORE = "APP_STORE"        # Apple App Store
    GOOGLE_PLAY = "GOOGLE_PLAY"    # Google Play


class StoreProductType(str, enum.Enum):
    APP = "APP"                    # платено приложение
    IN_APP = "IN_APP"              # вътрешнокупувателна покупка
    SUBSCRIPTION = "SUBSCRIPTION"  # абонамент


class StoreSale(UUIDMixin, TimestampMixin, Base):
    """Агрегиран ред продажби за (магазин, приложение, държава, ден, тип продукт)."""

    __tablename__ = "store_sales"
    __table_args__ = (
        UniqueConstraint("company_id", "source_ref", name="uq_store_sale_company_ref"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform: Mapped[StorePlatform] = mapped_column(
        SAEnum(StorePlatform, native_enum=False, length=20), index=True, nullable=False
    )
    report_date: Mapped[dt.date] = mapped_column(Date, index=True, nullable=False)
    app_name: Mapped[str] = mapped_column(String(200), nullable=False)
    app_identifier: Mapped[str] = mapped_column(String(200), nullable=False)  # bundle id / package / SKU
    product_type: Mapped[StoreProductType] = mapped_column(
        SAEnum(StoreProductType, native_enum=False, length=20), default=StoreProductType.APP, nullable=False
    )
    country: Mapped[str] = mapped_column(String(2), index=True, nullable=False)  # ISO-3166 alpha-2
    units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proceeds: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)  # приход за разработчика
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # Естествен ключ за дедупликация при повторно синхронизиране.
    source_ref: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
