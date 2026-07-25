"""Pydantic схеми за Companies модула."""
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.companies.models import CompanyRole


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    eik: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    country: str = Field(default="BG", min_length=2, max_length=2)
    base_currency: str = Field(default="EUR", min_length=3, max_length=3)
    is_vat_registered: bool = False


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    eik: str | None
    vat_number: str | None
    country: str
    base_currency: str
    is_vat_registered: bool
    is_active: bool


class CompanyWithRole(CompanyOut):
    """Компания заедно с ролята на текущия потребител в нея."""

    role: CompanyRole


# ---------- Членства / екип ----------
class MemberOut(BaseModel):
    id: uuid.UUID          # id на членството
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: CompanyRole


class MemberAdd(BaseModel):
    email: str = Field(max_length=255)
    role: CompanyRole


class MemberRoleUpdate(BaseModel):
    role: CompanyRole
