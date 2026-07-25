"""API рутер за получени фактури (AP, tenant-scoped)."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.purchases import service
from app.modules.purchases.schemas import PurchaseCreate, PurchaseOut

router = APIRouter(prefix="/purchase-invoices", tags=["purchases"])


@router.post("", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED, dependencies=[require("purchases.create")])
def create_purchase(data: PurchaseCreate, ctx: CurrentCompany, db: DbSession) -> PurchaseOut:
    inv = service.create_purchase(db, ctx.company, ctx.membership.user_id, data)
    return PurchaseOut.model_validate(inv)


@router.get("", response_model=list[PurchaseOut], dependencies=[require("purchases.view")])
def list_purchases(ctx: CurrentCompany, db: DbSession) -> list[PurchaseOut]:
    return [PurchaseOut.model_validate(i) for i in service.list_purchases(db, ctx.company.id)]


@router.get("/{invoice_id}", response_model=PurchaseOut, dependencies=[require("purchases.view")])
def get_purchase(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PurchaseOut:
    return PurchaseOut.model_validate(service.get_purchase(db, ctx.company.id, invoice_id))


@router.post("/{invoice_id}/post", response_model=PurchaseOut, dependencies=[require("purchases.post")])
def post_purchase(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PurchaseOut:
    inv = service.post_purchase(db, ctx.company, invoice_id, ctx.membership.user_id)
    return PurchaseOut.model_validate(inv)


@router.post("/{invoice_id}/cancel", response_model=PurchaseOut, dependencies=[require("purchases.create")])
def cancel_purchase(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> PurchaseOut:
    return PurchaseOut.model_validate(service.cancel_purchase(db, ctx.company.id, invoice_id))
