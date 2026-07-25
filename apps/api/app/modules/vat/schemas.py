"""Pydantic схеми за ДДС модула."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.vat.models import VatDirection


# ---------- ДДС кодове ----------
class VatCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=255)
    direction: VatDirection
    rate: Decimal = Field(default=Decimal("0.00"), ge=0, le=100, max_digits=5, decimal_places=2)
    gives_credit: bool = True
    requires_vies: bool = False
    requires_protocol: bool = False


class VatCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    direction: VatDirection
    rate: Decimal
    gives_credit: bool
    requires_vies: bool
    requires_protocol: bool
    is_active: bool


# ---------- ДДС записи ----------
class VatEntryCreate(BaseModel):
    vat_code_id: uuid.UUID
    document_date: dt.date
    tax_event_date: dt.date | None = None
    document_type: str | None = Field(default=None, max_length=50)
    document_number: str | None = Field(default=None, max_length=50)
    counterparty_name: str | None = Field(default=None, max_length=255)
    counterparty_vat_number: str | None = Field(default=None, max_length=20)
    # Може да е отрицателна при кредитни известия/корекции.
    tax_base: Decimal = Field(max_digits=18, decimal_places=2)
    # Ако е None, ДДС се изчислява автоматично от ставката на кода.
    vat_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    journal_entry_id: uuid.UUID | None = None


class VatEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_id: uuid.UUID
    vat_code_id: uuid.UUID
    direction: VatDirection
    document_type: str | None
    document_number: str | None
    document_date: dt.date
    tax_event_date: dt.date | None
    counterparty_name: str | None
    counterparty_vat_number: str | None
    tax_base: Decimal
    vat_amount: Decimal
    journal_entry_id: uuid.UUID | None


# ---------- Декларация / контроли ----------
class VatSideSummary(BaseModel):
    count: int
    total_base: Decimal
    total_vat: Decimal
    total_credit: Decimal = Decimal("0.00")  # само за покупки


class VatControl(BaseModel):
    level: str  # "ERROR" | "WARNING"
    code: str
    message: str
    vat_entry_id: uuid.UUID | None = None


class VatReturnOut(BaseModel):
    period_id: uuid.UUID
    period_code: str
    sales: VatSideSummary
    purchases: VatSideSummary
    vat_payable: Decimal      # ДДС за внасяне (ако е положително)
    vat_refundable: Decimal   # ДДС за възстановяване (ако е положително)
    controls: list[VatControl]
    has_blocking_errors: bool


# ---------- Справка-декларация по ЗДДС (НАП) ----------
class DeclarationCell(BaseModel):
    cell: str      # номер на клетката, напр. "01"
    label: str     # описание
    amount: Decimal


class VatDeclarationOut(BaseModel):
    period_id: uuid.UUID
    period_code: str        # ГГГГММ
    company_name: str
    company_vat_number: str | None
    cells: list[DeclarationCell]
    has_blocking_errors: bool
    controls: list[VatControl]
