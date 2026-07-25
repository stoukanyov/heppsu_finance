"""API за мобилния клиент: политика за версиите и отчети за сривове."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Header, HTTPException, Query, status

from app.api.deps import CurrentCompany, DbSession, require
from app.core.config import settings
from app.core.rate_limit import RateLimitRule, make_rate_limit_dependency
from app.core.security import decode_access_token
from app.modules.identity.models import User
from app.modules.mobile import service
from app.modules.mobile.schemas import (
    PLATFORMS,
    CrashGroup,
    CrashReportIn,
    CrashReportOut,
    ReleasePolicy,
)

logger = logging.getLogger("app.mobile")

router = APIRouter(prefix="/mobile", tags=["mobile"])

# Отчетите се приемат без автентикация (срив може да настъпи и на екрана за
# вход), затова единствената защита е ограничение по IP.
CrashRateLimit = make_rate_limit_dependency(
    "crash-report",
    lambda: RateLimitRule(
        max_attempts=settings.CRASH_REPORT_RATE_LIMIT,
        window_seconds=settings.CRASH_REPORT_RATE_WINDOW_SECONDS,
    ),
)


@router.get("/release", response_model=ReleasePolicy)
def release(
    platform: Annotated[str, Query(description="ios | android")] = "",
    version: Annotated[str | None, Query(description="Версия на клиента, напр. 1.4.2")] = None,
) -> ReleasePolicy:
    """Може ли тази версия да работи.

    Съзнателно **без автентикация**: клиент, който трябва да бъде спрян, често
    не може и да влезе (точно затова го спираме), а и проверката се прави преди
    екрана за вход.
    """
    normalized = platform.strip().lower()
    if normalized and normalized not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Непозната платформа: {platform}",
        )
    return service.release_policy(normalized, version)


@router.post("/crash", status_code=status.HTTP_202_ACCEPTED)
def submit_crash(
    data: CrashReportIn,
    db: DbSession,
    guard: CrashRateLimit,
    authorization: Annotated[str | None, Header()] = None,
    x_company_id: Annotated[uuid.UUID | None, Header(alias="X-Company-Id")] = None,
) -> dict[str, str]:
    """Приема отчет за срив от мобилния клиент.

    Връща 202, не 201: клиентът няма какво да прави с отговора и не бива да
    зависи от него — ако приемането се провали, докладът просто остава в
    локалната опашка за следващия опит.
    """
    if not settings.CRASH_REPORTING_ENABLED:
        # Изключено означава „не пращай повече“, а не „опитай пак“ — затова
        # не е грешка.
        return {"status": "disabled"}

    guard.check(
        "crash",
        detail="Твърде много отчети за сривове от този адрес. Опитайте по-късно.",
    )
    guard.register_event("crash")

    if data.platform.strip().lower() not in PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Непозната платформа: {data.platform}",
        )

    user_id = _user_id_from(db, authorization)
    service.record_crash(
        db,
        data,
        # Компанията се приема само ако знаем кой праща — иначе всеки може да
        # закачи докладите си за чужд тенант.
        company_id=x_company_id if user_id else None,
        user_id=user_id,
    )
    return {"status": "accepted"}


@router.get(
    "/crash-reports",
    response_model=list[CrashReportOut],
    dependencies=[require("audit.view")],
)
def list_crash_reports(
    ctx: CurrentCompany,  # noqa: ARG001 — тенант-скоупът е за проверката на правата
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CrashReportOut]:
    from sqlalchemy import select

    from app.modules.mobile.models import CrashReport

    rows = db.scalars(
        select(CrashReport).order_by(CrashReport.occurred_at.desc()).limit(limit)
    ).all()
    return [CrashReportOut.model_validate(r) for r in rows]


@router.get(
    "/crash-groups",
    response_model=list[CrashGroup],
    dependencies=[require("audit.view")],
)
def list_crash_groups(
    ctx: CurrentCompany,  # noqa: ARG001
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[CrashGroup]:
    return service.list_groups(db, limit=limit)


def _user_id_from(db: DbSession, authorization: str | None) -> uuid.UUID | None:
    """Меко разпознаване: валиден токен → потребител, всичко друго → анонимно.

    Не хвърляме при невалиден токен. Сривът често е точно това — счупена сесия;
    да откажем доклада заради нея значи да загубим следата от дефекта.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload.get("sub", ""))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
    user = db.get(User, user_id)
    return user.id if user and user.is_active else None
