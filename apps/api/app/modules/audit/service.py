"""Заявки към одитния журнал (само четене — журналът е неизменим)."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def list_logs(
    db: Session, company_id: uuid.UUID, method: str | None = None, limit: int = 200
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.company_id == company_id)
    if method:
        stmt = stmt.where(AuditLog.method == method.upper())
    return list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit)))


def get_log(db: Session, company_id: uuid.UUID, log_id: uuid.UUID) -> AuditLog | None:
    log = db.get(AuditLog, log_id)
    if log is None or log.company_id != company_id:
        return None
    return log
