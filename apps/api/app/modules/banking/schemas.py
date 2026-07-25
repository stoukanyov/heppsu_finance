"""Pydantic схеми за банковия модул."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.banking.models import BankTxStatus


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    iban: str | None = Field(default=None, max_length=34)
    bank_name: str | None = Field(default=None, max_length=255)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    gl_account_id: uuid.UUID | None = None


class BankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    iban: str | None
    bank_name: str | None
    currency: str
    gl_account_id: uuid.UUID | None
    is_active: bool


class BankTransactionIn(BaseModel):
    booking_date: dt.date
    value_date: dt.date | None = None
    amount: Decimal = Field(max_digits=18, decimal_places=2)  # знаково
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    counterparty_name: str | None = Field(default=None, max_length=255)
    counterparty_iban: str | None = Field(default=None, max_length=34)
    reference: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, max_length=64)


class ImportRequest(BaseModel):
    transactions: list[BankTransactionIn] = Field(min_length=1)


class ImportResult(BaseModel):
    imported: int
    duplicates: int


class BankTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_account_id: uuid.UUID
    booking_date: dt.date
    value_date: dt.date | None
    amount: Decimal
    currency: str
    counterparty_name: str | None
    counterparty_iban: str | None
    reference: str | None
    description: str | None
    status: BankTxStatus
    matched_amount: Decimal


class MatchSuggestion(BaseModel):
    journal_entry_id: uuid.UUID
    entry_number: int | None
    document_number: str | None
    document_date: dt.date
    amount: Decimal
    confidence: float
    reasons: list[str]


class MatchRequest(BaseModel):
    journal_entry_id: uuid.UUID
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    journal_entry_id: uuid.UUID
    amount: Decimal
    confidence: Decimal
    auto: bool
