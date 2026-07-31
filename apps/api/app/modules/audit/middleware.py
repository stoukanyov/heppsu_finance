"""Middleware, което записва променящите действия в одитния журнал."""
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.modules.audit.models import AuditLog

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

_log = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        try:
            path = request.url.path
            if (
                request.method in _MUTATING
                and path.startswith(settings.API_V1_PREFIX)
                and "/audit" not in path
            ):
                _record(request, path, response.status_code)
        except Exception:
            # Одитът не бива да чупи заявката — затова изключението се поглъща.
            # Но НЕ мълчаливо: `except: pass` тук значи, че журналът може да е с
            # дупки, без никой да разбере. За система, чието обещание е
            # проследимост на всяко действие, това е най-скъпият вид повреда:
            # открива се чак когато някой поиска одитната следа за спорен период.
            # `exception()` записва и traceback-а — иначе причината (пълна база,
            # заключена таблица, изтекла връзка) остава невидима.
            _log.exception(
                "Одитният запис за %s %s не беше направен — журналът е с дупка",
                request.method,
                request.url.path,
            )
        return response


def _record(request, path: str, status_code: int) -> None:
    user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = decode_access_token(auth.split(" ", 1)[1])
            user_id = uuid.UUID(payload.get("sub"))
        except Exception:
            user_id = None

    cid = request.headers.get("x-company-id")
    if cid:
        try:
            company_id = uuid.UUID(cid)
        except Exception:
            company_id = None

    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                company_id=company_id,
                method=request.method,
                path=path,
                status_code=status_code,
            )
        )
        db.commit()
    finally:
        db.close()
