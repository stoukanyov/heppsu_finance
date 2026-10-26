"""API рутер за модул „Магазини" (tenant-scoped)."""
import datetime as dt

from fastapi import APIRouter

from app.api.deps import CurrentCompany, DbSession, require
from app.core.config import settings
from app.modules.stores import service
from app.modules.stores.models import StorePlatform
from app.modules.stores.schemas import StoreAnalyticsOut, StoreSaleOut, SyncResult

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("/status")
def stores_status(ctx: CurrentCompany) -> dict:
    """Режимът на ВСЕКИ магазин поотделно.

    Беше една обща стойност и екранът показваше „Live · свързан“, щом е
    конфигуриран кой да е от двата магазина — тоест и за несвързания.
    `provider` остава за съвместимост (най-силният от двата режима).
    """
    po_magazin = {
        p.value: settings.store_provider_for(p.value) for p in StorePlatform
    }
    return {
        "provider": settings.resolved_store_provider,
        "platforms": po_magazin,
        "apple_configured": settings.apple_configured,
        "google_configured": settings.google_play_configured,
    }


@router.post("/{platform}/sync", response_model=SyncResult, dependencies=[require("stores.sync")])
def sync_store(
    platform: StorePlatform,
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date,
    date_to: dt.date,
) -> SyncResult:
    """Синхронизира продажбите от магазина за периода (записва нормализирано, дедупликирано)."""
    return service.sync_sales(db, ctx.company, platform, date_from, date_to)


@router.get("/sales", response_model=list[StoreSaleOut], dependencies=[require("stores.view")])
def list_sales(
    ctx: CurrentCompany, db: DbSession, platform: StorePlatform | None = None
) -> list[StoreSaleOut]:
    return [StoreSaleOut.model_validate(s) for s in service.list_sales(db, ctx.company.id, platform)]


@router.get("/analytics", response_model=StoreAnalyticsOut, dependencies=[require("stores.view")])
def analytics(
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    platform: StorePlatform | None = None,
) -> StoreAnalyticsOut:
    """Анализ: най-продавани приложения, по държави, по магазин и по месец."""
    return service.store_analytics(db, ctx.company, date_from, date_to, platform)
