"""Pydantic схеми за модул „Дълготрайни активи"."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.assets.models import AssetStatus, DepreciationMethod


class FixedAssetCreate(BaseModel):
    inventory_number: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    acquisition_date: dt.date
    in_service_date: dt.date
    initial_cost: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    residual_value: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    useful_life_months: int = Field(ge=1, le=1200)
    method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    location: str | None = Field(default=None, max_length=255)
    responsible_person: str | None = Field(default=None, max_length=255)
    gl_asset_account_id: uuid.UUID | None = None
    gl_expense_account_id: uuid.UUID | None = None
    gl_accum_account_id: uuid.UUID | None = None


class FixedAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inventory_number: str
    name: str
    category: str | None
    acquisition_date: dt.date
    in_service_date: dt.date
    initial_cost: Decimal
    residual_value: Decimal
    useful_life_months: int
    method: DepreciationMethod
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    status: AssetStatus
    location: str | None
    responsible_person: str | None
    gl_expense_account_id: uuid.UUID | None
    gl_accum_account_id: uuid.UUID | None


class ScheduleLine(BaseModel):
    year: int
    month: int
    amount: Decimal
    cumulative: Decimal


class DepreciationRunRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class DepreciationProposal(BaseModel):
    asset_id: uuid.UUID
    inventory_number: str
    name: str
    amount: Decimal


class DepreciateRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)


class DepreciationEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    year: int
    month: int
    amount: Decimal
    journal_entry_id: uuid.UUID | None
