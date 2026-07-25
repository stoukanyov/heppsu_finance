"""Pydantic схеми за платежните предложения."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.payments.models import PaymentStatus


class PaymentCreate(BaseModel):
    counterparty_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    recipient_iban: str | None = Field(default=None, max_length=34)
    due_date: dt.date | None = None
    priority: int = Field(default=0, ge=0, le=10)
    reference: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    counterparty_id: uuid.UUID
    recipient_name: str
    recipient_iban: str | None
    amount: Decimal
    currency: str
    due_date: dt.date | None
    priority: int
    reference: str | None
    notes: str | None
    status: PaymentStatus
    risk_flags: list[str]
    rejection_reason: str | None
    prepared_by_id: uuid.UUID
    approved_by_id: uuid.UUID | None
