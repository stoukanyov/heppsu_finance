"""Бизнес логика на модул „Магазини": синхронизиране и анализ на продажбите."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.stores.connectors.factory import get_connector
from app.modules.stores.models import StorePlatform, StoreSale
from app.modules.stores.schemas import (
    NamedTotal,
    StoreAnalyticsOut,
    SyncResult,
)

ZERO = Decimal("0.00")


def sync_sales(
    db: Session,
    company: Company,
    platform: StorePlatform,
    date_from: dt.date,
    date_to: dt.date,
) -> SyncResult:
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Крайната дата е преди началната")
    connector = get_connector(platform)
    data = connector.fetch_sales(date_from, date_to)

    existing = {
        ref for (ref,) in db.execute(
            select(StoreSale.source_ref).where(StoreSale.company_id == company.id)
        )
    }
    imported = duplicates = 0
    total = ZERO
    for row in data:
        ref = row.source_ref()
        total += row.proceeds
        if ref in existing:
            duplicates += 1
            continue
        existing.add(ref)
        db.add(StoreSale(
            company_id=company.id,
            platform=row.platform,
            report_date=row.report_date,
            app_name=row.app_name,
            app_identifier=row.app_identifier,
            product_type=row.product_type,
            country=row.country,
            units=row.units,
            proceeds=row.proceeds,
            currency=row.currency,
            source_ref=ref,
        ))
        imported += 1
    db.commit()
    return SyncResult(
        platform=platform, date_from=date_from, date_to=date_to,
        fetched=len(data), imported=imported, duplicates=duplicates,
        total_proceeds=total.quantize(Decimal("0.01")),
    )


def _rank(bucket: dict[str, list], top_n: int | None = None) -> list[NamedTotal]:
    items = [NamedTotal(key=k, units=u, proceeds=p.quantize(Decimal("0.01"))) for k, (u, p) in bucket.items()]
    items.sort(key=lambda x: (x.proceeds, x.units), reverse=True)
    return items[:top_n] if top_n else items


def store_analytics(
    db: Session,
    company: Company,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    platform: StorePlatform | None = None,
) -> StoreAnalyticsOut:
    stmt = select(StoreSale).where(StoreSale.company_id == company.id)
    if date_from:
        stmt = stmt.where(StoreSale.report_date >= date_from)
    if date_to:
        stmt = stmt.where(StoreSale.report_date <= date_to)
    if platform:
        stmt = stmt.where(StoreSale.platform == platform)
    sales = list(db.scalars(stmt))

    by_app: dict[str, list] = {}
    by_country: dict[str, list] = {}
    by_platform: dict[str, list] = {}
    by_month: dict[str, list] = {}
    total_units = 0
    total_proceeds = ZERO

    def add(bucket: dict, key: str, units: int, proceeds: Decimal):
        cur = bucket.setdefault(key, [0, ZERO])
        cur[0] += units
        cur[1] += proceeds

    labels = {StorePlatform.APP_STORE: "App Store", StorePlatform.GOOGLE_PLAY: "Google Play"}
    for s in sales:
        total_units += s.units
        total_proceeds += s.proceeds
        add(by_app, s.app_name, s.units, s.proceeds)
        add(by_country, s.country, s.units, s.proceeds)
        add(by_platform, labels[s.platform], s.units, s.proceeds)
        add(by_month, s.report_date.strftime("%Y-%m"), s.units, s.proceeds)

    ranked_app = _rank(by_app)
    ranked_country = _rank(by_country)
    months = sorted(
        (NamedTotal(key=k, units=u, proceeds=p.quantize(Decimal("0.01"))) for k, (u, p) in by_month.items()),
        key=lambda x: x.key,
    )
    return StoreAnalyticsOut(
        date_from=date_from, date_to=date_to,
        total_units=total_units,
        total_proceeds=total_proceeds.quantize(Decimal("0.01")),
        currency=company.base_currency,
        by_app=ranked_app,
        by_country=ranked_country,
        by_platform=_rank(by_platform),
        by_month=months,
        top_app=ranked_app[0].key if ranked_app else None,
        top_country=ranked_country[0].key if ranked_country else None,
    )


def list_sales(
    db: Session, company_id: uuid.UUID, platform: StorePlatform | None = None, limit: int = 200
) -> list[StoreSale]:
    stmt = select(StoreSale).where(StoreSale.company_id == company_id)
    if platform:
        stmt = stmt.where(StoreSale.platform == platform)
    return list(db.scalars(stmt.order_by(StoreSale.report_date.desc()).limit(limit)))
