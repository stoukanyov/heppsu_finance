"""API рутер за одитния журнал (само четене; журналът е неизменим)."""
import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentCompany, DbSession
from app.modules.audit import service

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    company_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    created_at: dt.datetime


@router.get("", response_model=list[AuditLogOut])
def list_audit(
    ctx: CurrentCompany, db: DbSession, method: str | None = None, limit: int = 200
) -> list[AuditLogOut]:
    logs = service.list_logs(db, ctx.company.id, method=method, limit=limit)
    return [AuditLogOut.model_validate(x) for x in logs]


@router.get("/{log_id}", response_model=AuditLogOut)
def get_audit(log_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> AuditLogOut:
    log = service.get_log(db, ctx.company.id, log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Записът не е намерен")
    return AuditLogOut.model_validate(log)
