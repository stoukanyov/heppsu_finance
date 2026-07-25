"""VAT Refund Procedure Engine — процедури по възстановяване на ДДС (чл. 92 ЗДДС).

Възстановяването НЕ е отделна декларация: то се заявява през месечната справка-декларация
и преминава през процедура, която трае няколко данъчни периода. Този модул следи цялата
процедура — възникване (клетка 60), двумесечно приспадане (клетки 70/71), остатък за
възстановяване (клетка 80), ускорено възстановяване (клетка 81) и режим по разрешение
(клетка 82) — заедно със сроковете, доказателствата и решенията на НАП.

ВАЖНО (Q-010): логиката отразява чл. 92 ЗДДС и указанията на НАП към 2026 г., но подлежи
на потвърждение от данъчен експерт и на тестване спрямо актуалния продукт „ДДС-документи"
на НАП преди реално ползване. Системата само подготвя — не подава декларации.
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

Money = Numeric(18, 2)
Ratio = Numeric(7, 4)
ZERO = Decimal("0.00")


class RefundProcedureType(str, enum.Enum):
    """Вид процедура по възстановяване."""

    STANDARD = "STANDARD"                    # чл. 92, ал. 1 — двумесечно приспадане
    ACCELERATED = "ACCELERATED"              # чл. 92, ал. 3 — ускорено (напр. >30% нулева ставка)
    INVESTMENT_PERMIT = "INVESTMENT_PERMIT"  # чл. 92, ал. 4 — разрешение по чл. 166


class RefundStatus(str, enum.Enum):
    """Състояния на процедурата (state machine).

    Стандартен път: CALCULATED → VAT_CREDIT_VALIDATED → DECLARED_IN_CELL_60 →
    OFFSET_PERIOD_1 → OFFSET_PERIOD_2 → READY_FOR_CELL_80 → SUBMITTED_FOR_REFUND →
    UNDER_NRA_CHECK → APPROVED/PARTIALLY_APPROVED/REFUSED/OFFSET_BY_NRA → PAID.

    Ускорен път: CALCULATED → ACCELERATED_ELIGIBILITY_CONFIRMED → USER_APPROVED →
    DECLARED_IN_CELL_81 → UNDER_NRA_CHECK → PAID/OFFSET_BY_NRA/REFUSED.
    """

    CALCULATED = "CALCULATED"
    VAT_CREDIT_VALIDATED = "VAT_CREDIT_VALIDATED"
    DECLARED_IN_CELL_60 = "DECLARED_IN_CELL_60"
    OFFSET_PERIOD_1 = "OFFSET_PERIOD_1"
    OFFSET_PERIOD_2 = "OFFSET_PERIOD_2"
    READY_FOR_CELL_80 = "READY_FOR_CELL_80"
    # Ускорена процедура
    ACCELERATED_ELIGIBILITY_CONFIRMED = "ACCELERATED_ELIGIBILITY_CONFIRMED"
    USER_APPROVED = "USER_APPROVED"
    DECLARED_IN_CELL_81 = "DECLARED_IN_CELL_81"
    DECLARED_IN_CELL_82 = "DECLARED_IN_CELL_82"
    # Общи финални състояния
    SUBMITTED_FOR_REFUND = "SUBMITTED_FOR_REFUND"
    UNDER_NRA_CHECK = "UNDER_NRA_CHECK"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REFUSED = "REFUSED"
    OFFSET_BY_NRA = "OFFSET_BY_NRA"
    PAID = "PAID"
    CLOSED = "CLOSED"


class NraCheckStatus(str, enum.Enum):
    NONE = "NONE"
    CHECK = "CHECK"          # проверка
    AUDIT = "AUDIT"          # ревизия
    SUSPENDED = "SUSPENDED"  # спрян срок (напр. непредставени документи)
    COMPLETED = "COMPLETED"


# Допустими преходи — процедурата не може да „скача" през етапи.
ALLOWED_TRANSITIONS: dict[RefundStatus, set[RefundStatus]] = {
    RefundStatus.CALCULATED: {
        RefundStatus.VAT_CREDIT_VALIDATED,
        RefundStatus.ACCELERATED_ELIGIBILITY_CONFIRMED,
        RefundStatus.CLOSED,
    },
    RefundStatus.VAT_CREDIT_VALIDATED: {
        RefundStatus.DECLARED_IN_CELL_60,
        RefundStatus.ACCELERATED_ELIGIBILITY_CONFIRMED,
        RefundStatus.CLOSED,
    },
    RefundStatus.DECLARED_IN_CELL_60: {RefundStatus.OFFSET_PERIOD_1, RefundStatus.CLOSED},
    RefundStatus.OFFSET_PERIOD_1: {RefundStatus.OFFSET_PERIOD_2, RefundStatus.CLOSED},
    RefundStatus.OFFSET_PERIOD_2: {RefundStatus.READY_FOR_CELL_80, RefundStatus.CLOSED},
    RefundStatus.READY_FOR_CELL_80: {RefundStatus.SUBMITTED_FOR_REFUND, RefundStatus.CLOSED},
    # Ускорена процедура: изисква изрично решение на потребителя
    RefundStatus.ACCELERATED_ELIGIBILITY_CONFIRMED: {
        RefundStatus.USER_APPROVED,
        RefundStatus.VAT_CREDIT_VALIDATED,  # отказ от ускорената → обратно към стандартната
        RefundStatus.CLOSED,
    },
    RefundStatus.USER_APPROVED: {
        RefundStatus.DECLARED_IN_CELL_81,
        RefundStatus.DECLARED_IN_CELL_82,
        RefundStatus.CLOSED,
    },
    RefundStatus.DECLARED_IN_CELL_81: {RefundStatus.SUBMITTED_FOR_REFUND, RefundStatus.UNDER_NRA_CHECK, RefundStatus.CLOSED},
    RefundStatus.DECLARED_IN_CELL_82: {RefundStatus.SUBMITTED_FOR_REFUND, RefundStatus.UNDER_NRA_CHECK, RefundStatus.CLOSED},
    RefundStatus.SUBMITTED_FOR_REFUND: {RefundStatus.UNDER_NRA_CHECK, RefundStatus.CLOSED},
    RefundStatus.UNDER_NRA_CHECK: {
        RefundStatus.APPROVED,
        RefundStatus.PARTIALLY_APPROVED,
        RefundStatus.REFUSED,
        RefundStatus.OFFSET_BY_NRA,
        RefundStatus.CLOSED,
    },
    RefundStatus.APPROVED: {RefundStatus.PAID, RefundStatus.OFFSET_BY_NRA, RefundStatus.CLOSED},
    RefundStatus.PARTIALLY_APPROVED: {RefundStatus.PAID, RefundStatus.OFFSET_BY_NRA, RefundStatus.CLOSED},
    RefundStatus.OFFSET_BY_NRA: {RefundStatus.PAID, RefundStatus.CLOSED},
    RefundStatus.REFUSED: {RefundStatus.CLOSED},
    RefundStatus.PAID: {RefundStatus.CLOSED},
    RefundStatus.CLOSED: set(),
}


class VatRefundProcedure(UUIDMixin, TimestampMixin, Base):
    """Една процедура по възстановяване, възникнала за конкретен данъчен период."""

    __tablename__ = "vat_refund_procedures"
    __table_args__ = (
        UniqueConstraint("company_id", "origin_period_id", name="uq_refund_company_origin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Периодът, в който е възникнал ДДС за възстановяване (клетка 60).
    origin_period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    original_refund_amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    amount_offset: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    remaining_refund: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    procedure_type: Mapped[RefundProcedureType] = mapped_column(
        SAEnum(RefundProcedureType, native_enum=False, length=25),
        default=RefundProcedureType.STANDARD, nullable=False,
    )
    legal_basis: Mapped[str] = mapped_column(String(120), default="чл. 92, ал. 1 ЗДДС", nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        SAEnum(RefundStatus, native_enum=False, length=40),
        default=RefundStatus.CALCULATED, index=True, nullable=False,
    )
    # Клетка от справка-декларацията, в която сумата се декларира (60/80/81/82).
    declaration_cell: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Двата последващи периода на приспадане по стандартната процедура.
    first_offset_period_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="SET NULL"), nullable=True
    )
    second_offset_period_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="SET NULL"), nullable=True
    )

    # Ускорена процедура (чл. 92, ал. 3): изчисленото съотношение и решението на потребителя.
    zero_rate_ratio: Mapped[Decimal | None] = mapped_column(Ratio, nullable=True)
    accelerated_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_approved_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    # Срокове и подаване
    submission_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    submission_deadline: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # 14-о число
    expected_refund_deadline: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # 30 дни

    # Решения на НАП
    nra_check_status: Mapped[NraCheckStatus] = mapped_column(
        SAEnum(NraCheckStatus, native_enum=False, length=15),
        default=NraCheckStatus.NONE, nullable=False,
    )
    offset_against_public_liabilities: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    nra_act_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    offsets: Mapped[list["VatRefundOffset"]] = relationship(
        back_populates="procedure", cascade="all, delete-orphan",
        order_by="VatRefundOffset.sequence",
    )


class VatRefundOffset(UUIDMixin, TimestampMixin, Base):
    """Приспадане на ДДС за внасяне през следващ период (клетки 70/71).

    По един запис на всеки от двата последващи периода. `amount` е приспаднатата част
    от натрупания остатък (клетка 70), а `payable_remaining` е това, което все още
    подлежи на внасяне (клетка 71).
    """

    __tablename__ = "vat_refund_offsets"
    __table_args__ = (
        UniqueConstraint("procedure_id", "period_id", name="uq_refund_offset_procedure_period"),
    )

    procedure_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vat_refund_procedures.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_periods.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1 или 2
    vat_payable_in_period: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)             # клетка 70
    payable_remaining: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)  # клетка 71
    refund_remaining_after: Mapped[Decimal] = mapped_column(Money, default=ZERO, nullable=False)

    procedure: Mapped["VatRefundProcedure"] = relationship(back_populates="offsets")
