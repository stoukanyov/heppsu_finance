"""API рутер за дълготрайни активи и амортизации (tenant-scoped)."""
import datetime as dt
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.assets import service
from app.modules.assets.schemas import (
    DepreciateRequest,
    DepreciationEntryOut,
    DepreciationProposal,
    DepreciationRunRequest,
    FixedAssetCreate,
    FixedAssetOut,
    ScheduleLine,
)

router = APIRouter(prefix="/fixed-assets", tags=["fixed-assets"])


@router.post("", response_model=FixedAssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(data: FixedAssetCreate, ctx: CurrentCompany, db: DbSession) -> FixedAssetOut:
    return FixedAssetOut.model_validate(service.create_asset(db, ctx.company.id, data))


@router.get("", response_model=list[FixedAssetOut])
def list_assets(ctx: CurrentCompany, db: DbSession) -> list[FixedAssetOut]:
    return [FixedAssetOut.model_validate(a) for a in service.list_assets(db, ctx.company.id)]


@router.get("/{asset_id}", response_model=FixedAssetOut)
def get_asset(asset_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> FixedAssetOut:
    return FixedAssetOut.model_validate(service.get_asset(db, ctx.company.id, asset_id))


@router.get("/{asset_id}/schedule", response_model=list[ScheduleLine])
def get_schedule(asset_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> list[ScheduleLine]:
    return service.schedule(db, ctx.company.id, asset_id)


@router.post("/depreciation-run", response_model=list[DepreciationProposal])
def depreciation_run(
    data: DepreciationRunRequest, ctx: CurrentCompany, db: DbSession
) -> list[DepreciationProposal]:
    """Предложения за месечна амортизация (системата предлага; осчетоводяването е отделно)."""
    return service.depreciation_run(db, ctx.company.id, data.year, data.month)


@router.post("/{asset_id}/depreciate", response_model=DepreciationEntryOut, status_code=status.HTTP_201_CREATED)
def depreciate(
    asset_id: uuid.UUID, data: DepreciateRequest, ctx: CurrentCompany, db: DbSession
) -> DepreciationEntryOut:
    depr = service.depreciate(db, ctx.company, asset_id, data.year, data.month, data.amount, ctx.membership.user_id)
    return DepreciationEntryOut.model_validate(depr)


@router.post("/{asset_id}/dispose", response_model=FixedAssetOut)
def dispose(asset_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> FixedAssetOut:
    return FixedAssetOut.model_validate(service.dispose(db, ctx.company.id, asset_id, dt.date.today()))
