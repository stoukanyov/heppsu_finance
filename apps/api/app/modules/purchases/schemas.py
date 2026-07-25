"""Pydantic схеми за получени фактури (AP)."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.purchases.models import PurchaseStatus


class PurchaseLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1.000"), gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class PurchaseLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_net: Decimal


class PurchaseCreate(BaseModel):
    counterparty_id: uuid.UUID
    supplier_document_number: str = Field(min_length=1, max_length=50)
    document_date: dt.date
    tax_event_date: dt.date | None = None
    due_date: dt.date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_code_id: uuid.UUID | None = None
    expense_account_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[PurchaseLineIn] = Field(min_length=1)


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    counterparty_id: uuid.UUID
    supplier_document_number: str
    document_date: dt.date
    tax_event_date: dt.date | None
    due_date: dt.date | None
    currency: str
    vat_code_id: uuid.UUID | None
    expense_account_id: uuid.UUID | None
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    status: PurchaseStatus
    notes: str | None
    document_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    vat_entry_id: uuid.UUID | None
    lines: list[PurchaseLineOut]
