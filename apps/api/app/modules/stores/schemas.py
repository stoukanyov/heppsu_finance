"""Pydantic схеми за модул „Магазини"."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.stores.models import StorePlatform, StoreProductType


class SyncResult(BaseModel):
    platform: StorePlatform
    date_from: dt.date
    date_to: dt.date
    fetched: int
    imported: int
    duplicates: int
    total_proceeds: Decimal


class StoreSaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: StorePlatform
    report_date: dt.date
    app_name: str
    app_identifier: str
    product_type: StoreProductType
    country: str
    units: int
    proceeds: Decimal
    currency: str


class NamedTotal(BaseModel):
    key: str          # име на приложение / държава / магазин / период
    units: int
    proceeds: Decimal


class StoreAnalyticsOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    total_units: int
    total_proceeds: Decimal
    currency: str
    by_app: list[NamedTotal]        # най-продавани приложения (подредени)
    by_country: list[NamedTotal]    # по държави
    by_platform: list[NamedTotal]   # App Store vs Google Play
    by_month: list[NamedTotal]      # времеви ред (ГГГГ-ММ)
    top_app: str | None
    top_country: str | None
