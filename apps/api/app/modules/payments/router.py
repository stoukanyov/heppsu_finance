"""API рутер за платежни предложения (tenant-scoped, maker-checker)."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.payments import service
from app.modules.payments.models import PaymentStatus
from app.modules.payments.schemas import PaymentCreate, PaymentOut, RejectRequest

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED, dependencies=[require("payments.prepare")])
def prepare_payment(data: PaymentCreate, ctx: CurrentCompany, db: DbSession) -> PaymentOut:
    """Подготвя платежно предложение (maker). Системата НЕ извършва плащането."""
    p = service.prepare(db, ctx.company, ctx.membership.user_id, data)
    return PaymentOut.model_validate(p)


@router.get("", response_model=list[PaymentOut], dependencies=[require("payments.view")])
def list_payments(
    ctx: CurrentCompany, db: DbSession, status: PaymentStatus | None = None
) -> list[PaymentOut]:
    return [PaymentOut.model_validate(p) for p in service.list_payments(db, ctx.company.id, status)]


@router.get("/{pid}", response_model=PaymentOut, dependencies=[require("payments.view")])
def get_payment(pid: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PaymentOut:
    return PaymentOut.model_validate(service.get_payment(db, ctx.company.id, pid))


@router.post("/{pid}/approve", response_model=PaymentOut, dependencies=[require("payments.approve")])
def approve_payment(pid: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PaymentOut:
    """Одобрява предложение (checker). Одобряващият трябва да е различен от подготвилия."""
    return PaymentOut.model_validate(service.approve(db, ctx.company.id, pid, ctx.membership.user_id))


@router.post("/{pid}/reject", response_model=PaymentOut, dependencies=[require("payments.approve")])
def reject_payment(pid: uuid.UUID, data: RejectRequest, ctx: CurrentCompany, db: DbSession) -> PaymentOut:
    return PaymentOut.model_validate(service.reject(db, ctx.company.id, pid, ctx.membership.user_id, data.reason))


@router.post("/{pid}/cancel", response_model=PaymentOut, dependencies=[require("payments.prepare")])
def cancel_payment(pid: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PaymentOut:
    return PaymentOut.model_validate(service.cancel(db, ctx.company.id, pid))
