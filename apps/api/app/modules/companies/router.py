"""API рутер за компании (tenant management)."""
from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, CurrentUser, DbSession
from app.modules.companies import service
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    CompanyWithRole,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyWithRole, status_code=status.HTTP_201_CREATED)
def create_company(data: CompanyCreate, user: CurrentUser, db: DbSession) -> CompanyWithRole:
    company, membership = service.create_company(db, data, owner_id=user.id)
    return CompanyWithRole(**CompanyOut.model_validate(company).model_dump(), role=membership.role)


@router.get("", response_model=list[CompanyWithRole])
def list_my_companies(user: CurrentUser, db: DbSession) -> list[CompanyWithRole]:
    result = service.list_companies_for_user(db, user.id)
    return [
        CompanyWithRole(**CompanyOut.model_validate(company).model_dump(), role=role)
        for company, role in result
    ]


@router.get("/current", response_model=CompanyWithRole)
def get_current_company(ctx: CurrentCompany) -> CompanyWithRole:
    """Връща активната компания (по header X-Company-Id) и ролята в нея."""
    return CompanyWithRole(**CompanyOut.model_validate(ctx.company).model_dump(), role=ctx.role)


@router.patch("/current", response_model=CompanyWithRole)
def update_current_company(
    data: CompanyUpdate, ctx: CurrentCompany, db: DbSession
) -> CompanyWithRole:
    """Обновява реквизитите на активната компания (само OWNER/управленски роли)."""
    from app.modules.companies.members_service import require_manage

    require_manage(ctx.role)
    company = service.update_company(db, ctx.company, data)
    return CompanyWithRole(**CompanyOut.model_validate(company).model_dump(), role=ctx.role)
