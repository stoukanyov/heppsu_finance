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
    fetched: int        # редове в отчета на магазина (преди събирането по ключ)
    imported: int       # нови редове
    updated: int = 0    # съществуващи редове с променени числа (магазинът е коригирал отчета)
    duplicates: int     # съществуващи редове без промяна
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
    # Валутата на реда, когато е ЕДНА. Празно значи „сборът е от повече от една
    # валута“ — тогава числото не бива да се показва с валутен знак. Реалните
    # отчети са многовалутни (един абонамент от Швейцария е в CHF, българският —
    # в EUR), а по-рано всичко се етикетираше с базовата валута на дружеството.
    currency: str = ""


class StoreAnalyticsOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    total_units: int
    total_proceeds: Decimal
    currency: str                   # празно, когато приходите са в повече от една валута
    by_currency: list[NamedTotal]   # приходите по валути — единственият верен сбор
    by_app: list[NamedTotal]        # най-продавани приложения (подредени)
    by_country: list[NamedTotal]    # по държави
    by_platform: list[NamedTotal]   # App Store vs Google Play
    by_month: list[NamedTotal]      # времеви ред (ГГГГ-ММ)
    top_app: str | None
    top_country: str | None
