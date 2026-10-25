"""Оферти — регистър на предложенията към клиенти.

Офертата е документ без счетоводен и данъчен ефект: тя не се осчетоводява, не
влиза в ДДС дневниците и не поражда вземане. Затова моделът е самостоятелен и
не докосва `journal_entries` или `vat_entries` — за разлика от фактурата.

Текстът се пази в `body` като лека разметка (виж `markup.py`), а позициите —
като отделни редове със свои числа. Таблицата нарочно НЕ е част от текста:
сумите трябва да се смятат, а не да се пишат.

Изтичането е **изведено**, не статус: `valid_until < днес` се вижда от датата и
не иска планировчик, който да обхожда записите и да ги маркира.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Date,
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
Qty = Numeric(18, 3)
Price = Numeric(18, 4)
Rate = Numeric(5, 2)
ZERO = Decimal("0.00")

# Префикс на номера: ОФ-0001. Фактурите ползват серия + 10 цифри, но офертата не е
# данъчен документ и няма изискване за формат — четимият номер е по-полезен.
NUMBER_PREFIX = "ОФ-"

# Срокът на офертата се мери по календара на клиента, не по часовника на сървъра.
_SOFIA = ZoneInfo("Europe/Sofia")


class OfferStatus(str, enum.Enum):
    DRAFT = "DRAFT"        # чернова — още се пише
    SENT = "SENT"          # изпратена на клиента
    ACCEPTED = "ACCEPTED"  # приета
    DECLINED = "DECLINED"  # отказана


class Offer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_offer_company_number"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("counterparties.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    issue_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Изчислена при запис от issue_date + validity_days; пази се, за да се
    # филтрира и подрежда в базата, вместо да се смята на всеки ред в приложението.
    valid_until: Mapped[dt.date] = mapped_column(Date, index=True, nullable=False)

    body: Mapped[str] = mapped_column(Text, default="", nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("20.00"), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    status: Mapped[OfferStatus] = mapped_column(
        SAEnum(OfferStatus, native_enum=False, length=10), default=OfferStatus.DRAFT, nullable=False
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    lines: Mapped[list[OfferLine]] = relationship(
        back_populates="offer", cascade="all, delete-orphan", order_by="OfferLine.line_no"
    )

    @property
    def full_number(self) -> str:
        return f"{NUMBER_PREFIX}{self.number:04d}"

    def is_expired(self, today: dt.date | None = None) -> bool:
        """Изтекла ли е офертата към даден ден (по подразбиране — днес).

        Денят е софийски, не UTC: сървърът върви в UTC и до 02:00 през лятото
        „днес" там е вчерашният ден — оферта, изтекла снощи, още се води валидна.
        """
        return self.valid_until < (today or dt.datetime.now(_SOFIA).date())


class OfferLine(UUIDMixin, Base):
    __tablename__ = "offer_lines"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1.000"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    line_net: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    offer: Mapped[Offer] = relationship(back_populates="lines")
