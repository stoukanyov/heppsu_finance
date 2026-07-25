"""API рутер за администраторския RBAC модул (tenant-scoped)."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.rbac import service
from app.modules.rbac.permissions import PERMISSIONS
from app.modules.rbac.schemas import (
    AssignRoleIn,
    MyAccessOut,
    PermissionGroupOut,
    PermissionOut,
    RoleCloneIn,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.get("/permissions", response_model=list[PermissionGroupOut])
def list_permissions() -> list[PermissionGroupOut]:
    """Каталогът на правата, групиран за администраторския екран."""
    return [
        PermissionGroupOut(
            group=group,
            permissions=[PermissionOut(code=c, label=l) for c, l in items],
        )
        for group, items in PERMISSIONS.items()
    ]


@router.get("/my-access", response_model=MyAccessOut)
def my_access(ctx: CurrentCompany, db: DbSession) -> MyAccessOut:
    """Правата на текущия потребител — мобилният клиент решава какво да покаже."""
    role = service.role_for_membership(db, ctx.membership)
    return MyAccessOut(
        role_id=role.id if role else None,
        role_code=role.code if role else None,
        role_name=role.name if role else None,
        permissions=sorted(service.permissions_for(db, ctx.membership)),
        can_use_mobile=service.can_use_mobile(db, ctx.membership),
        is_admin=service.is_admin(db, ctx.membership),
    )


@router.post("/roles/seed", response_model=list[RoleOut], status_code=status.HTTP_201_CREATED)
def seed_roles(ctx: CurrentCompany, db: DbSession) -> list[RoleOut]:
    """Създава предефинираните роли (Управител, Счетоводител и т.н.)."""
    service.require_admin(db, ctx.membership)
    service.seed_roles(db, ctx.company.id)
    return [RoleOut.model_validate(r) for r in service.list_roles(db, ctx.company.id)]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(ctx: CurrentCompany, db: DbSession) -> list[RoleOut]:
    service.require_permission(db, ctx.membership, "team.view")
    return [RoleOut.model_validate(r) for r in service.list_roles(db, ctx.company.id)]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(data: RoleCreate, ctx: CurrentCompany, db: DbSession) -> RoleOut:
    service.require_admin(db, ctx.membership)
    return RoleOut.model_validate(service.create_role(db, ctx.company.id, data))


@router.post("/roles/{role_id}/clone", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def clone_role(role_id: uuid.UUID, data: RoleCloneIn, ctx: CurrentCompany, db: DbSession) -> RoleOut:
    """Клонира роля в редактируемо копие (системните роли не се променят пряко)."""
    service.require_admin(db, ctx.membership)
    return RoleOut.model_validate(
        service.clone_role(db, ctx.company.id, role_id, data.code, data.name)
    )


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: uuid.UUID, data: RoleUpdate, ctx: CurrentCompany, db: DbSession) -> RoleOut:
    service.require_admin(db, ctx.membership)
    return RoleOut.model_validate(service.update_role(db, ctx.company.id, role_id, data))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> None:
    service.require_admin(db, ctx.membership)
    service.delete_role(db, ctx.company.id, role_id)


@router.post("/members/{membership_id}/role", response_model=MyAccessOut)
def assign_role(
    membership_id: uuid.UUID, data: AssignRoleIn, ctx: CurrentCompany, db: DbSession
) -> MyAccessOut:
    """Присвоява роля на член от екипа."""
    service.require_admin(db, ctx.membership)
    membership = service.assign_role(db, ctx.company.id, membership_id, data.role_id)
    role = service.role_for_membership(db, membership)
    return MyAccessOut(
        role_id=role.id if role else None,
        role_code=role.code if role else None,
        role_name=role.name if role else None,
        permissions=sorted(service.permissions_for(db, membership)),
        can_use_mobile=service.can_use_mobile(db, membership),
        is_admin=service.is_admin(db, membership),
    )
