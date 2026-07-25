"""API рутер за управление на екипа (членства) на текущата компания."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.companies import members_service as service
from app.modules.companies.schemas import MemberAdd, MemberOut, MemberRoleUpdate

router = APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=list[MemberOut])
def list_members(ctx: CurrentCompany, db: DbSession) -> list[MemberOut]:
    return [MemberOut(**m) for m in service.list_members(db, ctx.company.id)]


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(data: MemberAdd, ctx: CurrentCompany, db: DbSession) -> MemberOut:
    service.require_manage(ctx.role)
    return MemberOut(**service.add_member(db, ctx.company.id, data.email, data.role))


@router.patch("/{membership_id}", response_model=MemberOut)
def update_member_role(
    membership_id: uuid.UUID, data: MemberRoleUpdate, ctx: CurrentCompany, db: DbSession
) -> MemberOut:
    service.require_manage(ctx.role)
    return MemberOut(**service.update_role(db, ctx.company.id, membership_id, data.role))


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(membership_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> None:
    service.require_manage(ctx.role)
    service.remove_member(db, ctx.company.id, membership_id)
