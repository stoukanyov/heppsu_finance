"""Pydantic схеми за регистъра на контрагенти."""
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.counterparties.models import CounterpartyType


class BankAccountIn(BaseModel):
    iban: str = Field(min_length=5, max_length=34)
    bank_name: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_primary: bool = False


class BankAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    iban: str
    bank_name: str | None
    currency: str | None
    is_primary: bool


class CounterpartyBase(BaseModel):
    type: CounterpartyType
    name: str = Field(min_length=1, max_length=255)
    eik: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    country: str = Field(default="BG", min_length=2, max_length=2)
    address: str | None = Field(default=None, max_length=500)
    contact_person: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    tax_status: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    default_account_id: uuid.UUID | None = None
    default_vat_code_id: uuid.UUID | None = None


class CounterpartyCreate(CounterpartyBase):
    bank_accounts: list[BankAccountIn] = []


class CounterpartyUpdate(BaseModel):
    """Частично обновяване — всички полета по избор."""

    type: CounterpartyType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    eik: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    address: str | None = Field(default=None, max_length=500)
    contact_person: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    tax_status: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    default_account_id: uuid.UUID | None = None
    default_vat_code_id: uuid.UUID | None = None
    is_active: bool | None = None
    bank_accounts: list[BankAccountIn] | None = None


class CounterpartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: CounterpartyType
    name: str
    eik: str | None
    vat_number: str | None
    country: str
    address: str | None
    contact_person: str | None
    email: str | None
    phone: str | None
    preferred_currency: str | None
    payment_terms_days: int | None
    credit_limit: Decimal | None
    tax_status: str | None
    notes: str | None
    default_account_id: uuid.UUID | None
    default_vat_code_id: uuid.UUID | None
    is_active: bool
    bank_accounts: list[BankAccountOut]


class DuplicateCheckRequest(BaseModel):
    name: str | None = None
    eik: str | None = None
    vat_number: str | None = None
    iban: str | None = None


class DuplicateMatch(BaseModel):
    id: uuid.UUID
    name: str
    eik: str | None
    vat_number: str | None
    reasons: list[str]
