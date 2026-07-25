"""Pydantic схеми за счетоводното ядро."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.accounting.models import (
    AccountType,
    EntryStatus,
    JournalType,
    PeriodStatus,
)


# ---------- Сметкоплан ----------
class AccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=255)
    type: AccountType
    parent_id: uuid.UUID | None = None
    is_group: bool = False
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    type: AccountType
    parent_id: uuid.UUID | None
    is_group: bool
    currency: str | None
    is_active: bool


# ---------- Периоди ----------
class FiscalYearCreate(BaseModel):
    year: int = Field(ge=2000, le=2100)
    # По подразбиране: календарна година + 12 месечни периода.
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    start_date: dt.date
    end_date: dt.date
    status: PeriodStatus


class FiscalYearOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    year: int
    start_date: dt.date
    end_date: dt.date
    is_closed: bool
    periods: list[PeriodOut] = []


class PeriodStatusUpdate(BaseModel):
    status: PeriodStatus


# ---------- Счетоводни операции ----------
class JournalLineIn(BaseModel):
    account_id: uuid.UUID
    debit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    credit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    description: str | None = Field(default=None, max_length=500)


class JournalLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_no: int
    account_id: uuid.UUID
    debit: Decimal
    credit: Decimal
    debit_base: Decimal
    credit_base: Decimal
    description: str | None
    # Изведени от сметката, за да не се налага клиентът да прави отделна заявка.
    account_code: str | None = None
    account_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _expand_account(cls, data):
        """Разгъва свързаната сметка в код и наименование при валидиране от ORM обект."""
        account = getattr(data, "account", None)
        if account is None:
            return data
        return {
            "id": data.id,
            "line_no": data.line_no,
            "account_id": data.account_id,
            "debit": data.debit,
            "credit": data.credit,
            "debit_base": data.debit_base,
            "credit_base": data.credit_base,
            "description": data.description,
            "account_code": account.code,
            "account_name": account.name,
        }


class JournalEntryCreate(BaseModel):
    document_date: dt.date
    journal: JournalType = JournalType.GENERAL
    document_type: str | None = Field(default=None, max_length=50)
    document_number: str | None = Field(default=None, max_length=50)
    tax_event_date: dt.date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rate: Decimal = Field(default=Decimal("1.000000"), gt=0, max_digits=18, decimal_places=6)
    description: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineIn] = Field(min_length=2)


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_number: int | None
    journal: JournalType
    document_type: str | None
    document_number: str | None
    document_date: dt.date
    tax_event_date: dt.date | None
    posting_date: dt.date | None
    currency: str
    exchange_rate: Decimal
    description: str | None
    status: EntryStatus
    period_id: uuid.UUID
    reverses_entry_id: uuid.UUID | None
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalLineOut]
