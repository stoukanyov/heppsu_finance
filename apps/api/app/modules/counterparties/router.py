"""API рутер за контрагенти (tenant-scoped)."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.counterparties import service
from app.modules.counterparties.models import CounterpartyType
from app.modules.counterparties.schemas import (
    CounterpartyCreate,
    CounterpartyOut,
    CounterpartyUpdate,
    DuplicateCheckRequest,
    DuplicateMatch,
)

router = APIRouter(prefix="/counterparties", tags=["counterparties"])


@router.post("", response_model=CounterpartyOut, status_code=status.HTTP_201_CREATED, dependencies=[require("counterparties.manage")])
def create_counterparty(
    data: CounterpartyCreate, ctx: CurrentCompany, db: DbSession
) -> CounterpartyOut:
    cp = service.create_counterparty(db, ctx.company.id, data)
    return CounterpartyOut.model_validate(cp)


@router.get("", response_model=list[CounterpartyOut], dependencies=[require("counterparties.view")])
def list_counterparties(
    ctx: CurrentCompany,
    db: DbSession,
    type: CounterpartyType | None = None,
    q: str | None = None,
) -> list[CounterpartyOut]:
    items = service.list_counterparties(db, ctx.company.id, type_filter=type, q=q)
    return [CounterpartyOut.model_validate(cp) for cp in items]


@router.post("/check-duplicates", response_model=list[DuplicateMatch], dependencies=[require("counterparties.manage")])
def check_duplicates(
    req: DuplicateCheckRequest, ctx: CurrentCompany, db: DbSession
) -> list[DuplicateMatch]:
    return service.find_duplicates(db, ctx.company.id, req)


@router.get("/{cp_id}", response_model=CounterpartyOut, dependencies=[require("counterparties.view")])
def get_counterparty(cp_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> CounterpartyOut:
    return CounterpartyOut.model_validate(service.get_counterparty(db, ctx.company.id, cp_id))


@router.patch("/{cp_id}", response_model=CounterpartyOut, dependencies=[require("counterparties.manage")])
def update_counterparty(
    cp_id: uuid.UUID, data: CounterpartyUpdate, ctx: CurrentCompany, db: DbSession
) -> CounterpartyOut:
    return CounterpartyOut.model_validate(
        service.update_counterparty(db, ctx.company.id, cp_id, data)
    )
