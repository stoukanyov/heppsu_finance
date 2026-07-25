"""API рутер за календара със сроковете (tenant-scoped чрез X-Company-Id).

Само за четене — модулът нищо не записва. Мобилното приложение ползва ``key``, за да
не дублира вече планирано напомняне.
"""
import datetime as dt

from fastapi import APIRouter, Query

from app.api.deps import CurrentCompany, DbSession
from app.modules.deadlines import service
from app.modules.deadlines.schemas import DeadlineOut

router = APIRouter(prefix="/deadlines", tags=["deadlines"])


@router.get("/upcoming", response_model=list[DeadlineOut])
def upcoming(
    ctx: CurrentCompany,
    db: DbSession,
    days_ahead: int = Query(service.DEFAULT_DAYS_AHEAD, ge=1, le=service.MAX_DAYS_AHEAD),
    reference_date: dt.date | None = Query(
        None, description="Отправна дата (по подразбиране днес) — прави отговора детерминиран."
    ),
) -> list[DeadlineOut]:
    """Предстоящите срокове към НАП, НСИ и Търговския регистър, сортирани по дата."""
    return service.upcoming_deadlines(
        db, ctx.company, reference_date=reference_date, days_ahead=days_ahead
    )
