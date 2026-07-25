"""Pydantic схеми за модул „Фактуриране"."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.invoicing.models import InvoiceStatus, InvoiceType


class InvoiceLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1.000"), gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_net: Decimal


class InvoiceCreate(BaseModel):
    counterparty_id: uuid.UUID
    invoice_type: InvoiceType = InvoiceType.INVOICE
    series: str = Field(default="", max_length=10)
    issue_date: dt.date
    tax_event_date: dt.date | None = None
    due_date: dt.date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_code_id: uuid.UUID | None = None
    original_invoice_id: uuid.UUID | None = None  # за кредитно/дебитно известие
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[InvoiceLineIn] = Field(min_length=1)


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    counterparty_id: uuid.UUID
    invoice_type: InvoiceType
    series: str
    number: int | None
    full_number: str | None
    issue_date: dt.date
    tax_event_date: dt.date | None
    due_date: dt.date | None
    currency: str
    vat_code_id: uuid.UUID | None
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    status: InvoiceStatus
    notes: str | None
    journal_entry_id: uuid.UUID | None
    vat_entry_id: uuid.UUID | None
    original_invoice_id: uuid.UUID | None
    lines: list[InvoiceLineOut]
