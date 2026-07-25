"""Pydantic схеми за RBAC модула."""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)
    can_use_mobile: bool = False
    is_admin: bool = False


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None
    can_use_mobile: bool | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


class RoleCloneIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    permissions: list[str]
    can_use_mobile: bool
    is_admin: bool
    is_system: bool
    is_active: bool


class PermissionOut(BaseModel):
    code: str
    label: str


class PermissionGroupOut(BaseModel):
    group: str
    permissions: list[PermissionOut]


class MyAccessOut(BaseModel):
    """Какво може текущият потребител — ползва се и от мобилния клиент."""

    role_id: uuid.UUID | None
    role_code: str | None
    role_name: str | None
    permissions: list[str]
    can_use_mobile: bool
    is_admin: bool


class AssignRoleIn(BaseModel):
    role_id: uuid.UUID | None = None
