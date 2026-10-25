"""Pydantic схеми за модул „Оферти"."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.offers.models import OfferStatus

# Горна граница на валидността: 10 години. Не е бизнес правило, а предпазител —
# `issue_date + validity_days` трябва да остане валидна дата.
MAX_VALIDITY_DAYS = 3650


class OfferLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal = Field(default=Decimal("1.000"), gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class OfferLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    description: str
    unit: str | None
    quantity: Decimal
    unit_price: Decimal
    line_net: Decimal


class OfferCreate(BaseModel):
    counterparty_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    issue_date: dt.date
    validity_days: int = Field(ge=1, le=MAX_VALIDITY_DAYS)
    body: str = Field(default="", max_length=40000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_rate: Decimal = Field(default=Decimal("20.00"), ge=0, le=100, max_digits=5, decimal_places=2)
    lines: list[OfferLineIn] = Field(default_factory=list, max_length=200)


class OfferUpdate(BaseModel):
    """Редакция на оферта. Подадените полета се заместват, останалите остават."""

    counterparty_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    issue_date: dt.date | None = None
    validity_days: int | None = Field(default=None, ge=1, le=MAX_VALIDITY_DAYS)
    body: str | None = Field(default=None, max_length=40000)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    status: OfferStatus | None = None
    # `None` = не пипай позициите; `[]` = изтрий ги всичките.
    lines: list[OfferLineIn] | None = Field(default=None, max_length=200)


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    counterparty_id: uuid.UUID
    counterparty_name: str | None = None
    number: int
    full_number: str
    title: str
    issue_date: dt.date
    validity_days: int
    valid_until: dt.date
    is_expired: bool
    body: str
    currency: str
    vat_rate: Decimal
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    status: OfferStatus
    lines: list[OfferLineOut]


class OfferPreviewRequest(BaseModel):
    """Текст и позиции, които още не са записани — за прегледа преди запис."""

    title: str = Field(default="", max_length=255)
    issue_date: dt.date | None = None
    validity_days: int | None = Field(default=None, ge=1, le=MAX_VALIDITY_DAYS)
    body: str = Field(default="", max_length=40000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_rate: Decimal = Field(default=Decimal("20.00"), ge=0, le=100, max_digits=5, decimal_places=2)
    lines: list[OfferLineIn] = Field(default_factory=list, max_length=200)


class PreviewLine(BaseModel):
    line_no: int
    description: str
    unit: str | None
    quantity: Decimal
    unit_price: Decimal
    line_net: Decimal


class OfferPreviewOut(BaseModel):
    """Готовият за рисуване документ: блокове от текста плюс сметката."""

    blocks: list[dict]
    lines: list[PreviewLine]
    has_items_marker: bool
    valid_until: dt.date | None
    currency: str
    vat_rate: Decimal
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
