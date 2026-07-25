"""API рутер за календара със сроковете (tenant-scoped чрез X-Company-Id).

Изчисляването е само за четене — модулът пази единствено отметките „подадено“.
Мобилното приложение ползва ``key``, за да не дублира вече планирано напомняне.
"""
import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.deadlines import service
from app.modules.deadlines.schemas import DeadlineOut, FilingOut, FilingRequest

router = APIRouter(prefix="/deadlines", tags=["deadlines"])


@router.get("/upcoming", response_model=list[DeadlineOut])
def upcoming(
    ctx: CurrentCompany,
    db: DbSession,
    days_ahead: int = Query(service.DEFAULT_DAYS_AHEAD, ge=1, le=service.MAX_DAYS_AHEAD),
    reference_date: dt.date | None = Query(
        None, description="Отправна дата (по подразбиране днес) — прави отговора детерминиран."
    ),
    include_filed: bool = Query(
        True, description="Дали да включва вече отметнатите като подадени."
    ),
) -> list[DeadlineOut]:
    """Предстоящите срокове към НАП, НСИ и Търговския регистър, сортирани по дата."""
    return service.upcoming_deadlines(
        db,
        ctx.company,
        reference_date=reference_date,
        days_ahead=days_ahead,
        include_filed=include_filed,
    )


@router.get("/filings", response_model=list[FilingOut])
def filings(ctx: CurrentCompany, db: DbSession) -> list[FilingOut]:
    """Отметките „подадено“ на компанията, най-скорошните първи."""
    return [FilingOut.model_validate(f) for f in service.list_filings(db, ctx.company.id)]


@router.post("/filings", response_model=FilingOut, status_code=status.HTTP_201_CREATED)
def mark_filed(data: FilingRequest, ctx: CurrentCompany, db: DbSession) -> FilingOut:
    """Отмята срок като подаден.

    Идемпотентно: повторно натискане не е грешка, а обновяване на бележката.
    """
    filing = service.mark_filed(
        db, ctx.company.id, ctx.membership.user_id, data.key, data.note
    )
    return FilingOut.model_validate(filing)


@router.delete("/filings", status_code=status.HTTP_204_NO_CONTENT)
def unmark_filed(
    ctx: CurrentCompany,
    db: DbSession,
    key: Annotated[str, Query(min_length=1, max_length=120)],
) -> None:
    """Маха отметката — за поправяне на грешно отметнат срок.

    Ключът е query параметър, а не част от пътя: съдържа двоеточие
    (``vat-return:2026-07``) и кодирането му в пътя е излишен източник на грешки.
    """
    service.unmark_filed(db, ctx.company.id, key)
