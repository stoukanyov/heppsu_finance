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
    """Показва режима (live/stub) и кои магазини са конфигурирани."""
    return {
        "provider": settings.resolved_store_provider,
        "apple_configured": bool(settings.APPLE_ISSUER_ID and settings.APPLE_PRIVATE_KEY_PATH),
        "google_configured": bool(settings.GOOGLE_PLAY_BUCKET and settings.GOOGLE_APPLICATION_CREDENTIALS),
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
