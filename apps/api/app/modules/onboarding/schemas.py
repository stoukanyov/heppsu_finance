"""Pydantic схеми за въвеждането на клиент."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class OpeningBalanceRow(BaseModel):
    account_code: str = Field(min_length=1, max_length=20)
    debit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    credit: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)


class OpeningBalancesIn(BaseModel):
    on_date: dt.date | None = None
    rows: list[OpeningBalanceRow] = Field(min_length=1, max_length=5000)


class ResolvedBalanceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    debit: Decimal
    credit: Decimal


class OpeningBalancesPreviewOut(BaseModel):
    rows: list[ResolvedBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    balanced: bool
    problems: list[str]
    can_post: bool


class PostedEntryOut(BaseModel):
    id: uuid.UUID
    entry_number: int | None = None
    document_date: dt.date
