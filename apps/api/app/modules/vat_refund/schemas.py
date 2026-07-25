"""Pydantic схеми за процедурите по възстановяване на ДДС."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.vat_refund.models import (
    NraCheckStatus,
    RefundProcedureType,
    RefundStatus,
)


class RefundOffsetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_id: uuid.UUID
    sequence: int
    vat_payable_in_period: Decimal   # ДДС за внасяне в периода (клетка 50)
    amount: Decimal                  # приспаднато (клетка 70)
    payable_remaining: Decimal       # за внасяне след приспадането (клетка 71)
    refund_remaining_after: Decimal  # остатък за възстановяване след приспадането


class AcceleratedCheckOut(BaseModel):
    """Резултат от проверката за ускорено възстановяване (чл. 92, ал. 3)."""

    eligible: bool
    zero_rate_amount: Decimal
    taxable_amount: Decimal
    ratio_percent: Decimal      # напр. 37.4
    threshold_percent: Decimal  # напр. 30.0
    period_from: dt.date
    period_to: dt.date
    legal_basis: str
    reasons: list[str] = []
    # Ускорената процедура НЕ се прилага автоматично — изисква изрично решение.
    requires_user_approval: bool = True


class RefundValidationOut(BaseModel):
    level: str   # ERROR | WARNING | INFO
    code: str
    message: str


class VatRefundProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    origin_period_id: uuid.UUID
    original_refund_amount: Decimal
    amount_offset: Decimal
    remaining_refund: Decimal
    procedure_type: RefundProcedureType
    legal_basis: str
    status: RefundStatus
    declaration_cell: str | None
    first_offset_period_id: uuid.UUID | None
    second_offset_period_id: uuid.UUID | None
    zero_rate_ratio: Decimal | None
    accelerated_eligible: bool
    submission_date: dt.date | None
    submission_deadline: dt.date | None
    expected_refund_deadline: dt.date | None
    nra_check_status: NraCheckStatus
    offset_against_public_liabilities: Decimal
    amount_paid: Decimal
    nra_act_reference: str | None
    notes: str | None
    offsets: list[RefundOffsetOut] = []


class VatRefundOverviewOut(BaseModel):
    """Пълна картина за екрана: процедурата + сроковете + следващата стъпка."""

    procedure: VatRefundProcedureOut
    origin_period_code: str
    first_offset_period_code: str | None
    second_offset_period_code: str | None
    expected_completion_period_code: str | None
    next_action: str            # какво следва на човешки език
    accelerated: AcceleratedCheckOut | None = None
    validations: list[RefundValidationOut] = []


class RefundDecisionIn(BaseModel):
    """Решение на НАП по процедурата."""

    approved_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    offset_against_public_liabilities: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    nra_act_reference: str | None = Field(default=None, max_length=120)
    nra_check_status: NraCheckStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RefundPaymentIn(BaseModel):
    amount_paid: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    nra_act_reference: str | None = Field(default=None, max_length=120)


class AcceleratedElectionIn(BaseModel):
    """Изрично потвърждение за деклариране в клетка 81 (или 82 при разрешение)."""

    confirm: bool = Field(description="Потребителят желае ускорена процедура")
    investment_permit_number: str | None = Field(
        default=None, max_length=120,
        description="Разрешение по чл. 166 ЗДДС — активира клетка 82 (чл. 92, ал. 4)",
    )
