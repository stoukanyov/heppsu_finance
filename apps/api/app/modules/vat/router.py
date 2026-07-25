"""API рутер за ДДС модула (tenant-scoped чрез X-Company-Id)."""
import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.vat import service
from app.modules.vat.models import VatDirection
from app.modules.vat.schemas import (
    VatCodeCreate,
    VatCodeOut,
    VatControl,
    VatDeclarationOut,
    VatEntryCreate,
    VatEntryOut,
    VatPeriodClosingOut,
    VatPeriodRejectIn,
    VatPeriodSummaryOut,
    VatReturnOut,
)

router = APIRouter(prefix="/vat", tags=["vat"])


# ---------- ДДС кодове ----------
@router.post("/codes/seed", response_model=list[VatCodeOut], status_code=status.HTTP_201_CREATED, dependencies=[require("vat.manage")])
def seed_vat_codes(ctx: CurrentCompany, db: DbSession) -> list[VatCodeOut]:
    service.seed_standard_vat_codes(db, ctx.company.id)
    return [VatCodeOut.model_validate(c) for c in service.list_vat_codes(db, ctx.company.id)]


@router.post("/codes", response_model=VatCodeOut, status_code=status.HTTP_201_CREATED, dependencies=[require("vat.manage")])
def create_vat_code(data: VatCodeCreate, ctx: CurrentCompany, db: DbSession) -> VatCodeOut:
    return VatCodeOut.model_validate(service.create_vat_code(db, ctx.company.id, data))


@router.get("/codes", response_model=list[VatCodeOut], dependencies=[require("vat.view")])
def list_vat_codes(ctx: CurrentCompany, db: DbSession) -> list[VatCodeOut]:
    return [VatCodeOut.model_validate(c) for c in service.list_vat_codes(db, ctx.company.id)]


# ---------- ДДС записи ----------
@router.post("/entries", response_model=VatEntryOut, status_code=status.HTTP_201_CREATED, dependencies=[require("vat.manage")])
def create_vat_entry(data: VatEntryCreate, ctx: CurrentCompany, db: DbSession) -> VatEntryOut:
    entry = service.create_vat_entry(db, ctx.company.id, ctx.membership.user_id, data)
    return VatEntryOut.model_validate(entry)


@router.get("/entries", response_model=list[VatEntryOut], dependencies=[require("vat.view")])
def list_vat_entries(
    ctx: CurrentCompany,
    db: DbSession,
    period_id: uuid.UUID | None = None,
    direction: VatDirection | None = None,
) -> list[VatEntryOut]:
    entries = service.list_vat_entries(db, ctx.company.id, period_id=period_id, direction=direction)
    return [VatEntryOut.model_validate(e) for e in entries]


# ---------- Декларация и контроли ----------
@router.get("/returns/{period_id}", response_model=VatReturnOut, dependencies=[require("vat.view")])
def get_vat_return(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> VatReturnOut:
    return service.get_vat_return(db, ctx.company.id, period_id)


@router.get("/periods/{period_id}/controls", response_model=list[VatControl], dependencies=[require("vat.view")])
def get_vat_controls(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> list[VatControl]:
    return service.vat_period_controls(db, ctx.company.id, period_id)


# ---------- Списък с ДДС периоди (одобрение / отказ) ----------
@router.get("/periods", response_model=list[VatPeriodSummaryOut], dependencies=[require("vat.view")])
def list_vat_periods(ctx: CurrentCompany, db: DbSession) -> list[VatPeriodSummaryOut]:
    """Месечните ДДС отчети със статус и суми — най-новите първи."""
    return service.list_vat_periods(db, ctx.company.id)


@router.post("/periods/{period_id}/reject", response_model=VatPeriodSummaryOut, dependencies=[require("vat.close_period")])
def reject_vat_period(
    period_id: uuid.UUID, data: VatPeriodRejectIn, ctx: CurrentCompany, db: DbSession
) -> VatPeriodSummaryOut:
    """Връща ДДС периода за корекция. Одобрението минава през POST /periods/{id}/close."""
    return service.reject_vat_period(db, ctx.company.id, ctx.membership.user_id, period_id, data)


# ---------- Приключване на ДДС период ----------
@router.post("/periods/{period_id}/close", response_model=VatPeriodClosingOut, status_code=status.HTTP_201_CREATED, dependencies=[require("vat.close_period")])
def close_vat_period(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> VatPeriodClosingOut:
    closing = service.close_vat_period(db, ctx.company.id, ctx.membership.user_id, period_id)
    return VatPeriodClosingOut.model_validate(closing)


@router.get("/periods/{period_id}/closing", response_model=VatPeriodClosingOut | None, dependencies=[require("vat.view")])
def get_vat_closing(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> VatPeriodClosingOut | None:
    closing = service.get_vat_closing(db, ctx.company.id, period_id)
    return VatPeriodClosingOut.model_validate(closing) if closing else None


# ---------- Справка-декларация по ЗДДС и файлове за НАП ----------
@router.get("/returns/{period_id}/declaration", response_model=VatDeclarationOut, dependencies=[require("vat.view")])
def get_vat_declaration(
    period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession
) -> VatDeclarationOut:
    return service.get_vat_declaration(db, ctx.company.id, period_id)


@router.get("/returns/{period_id}/nap-files", dependencies=[require("vat.view")])
def download_nap_files(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    zip_bytes, filename = service.build_nap_files(db, ctx.company.id, period_id)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
