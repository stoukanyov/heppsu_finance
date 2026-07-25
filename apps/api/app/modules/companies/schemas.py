"""Pydantic схеми за Companies модула."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.companies.models import CompanyRole


class CompanyDetails(BaseModel):
    """Реквизити на дружеството — ползват се във фактури, декларации и НАП файлове."""

    name_latin: str | None = Field(default=None, max_length=255)
    legal_form: str | None = Field(default=None, max_length=50)
    address_city: str | None = Field(default=None, max_length=120)
    address_postcode: str | None = Field(default=None, max_length=10)
    address_line: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    owner_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    activity: str | None = Field(default=None, max_length=500)
    vat_registration_date: dt.date | None = None
    incorporation_date: dt.date | None = None
    share_capital: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class CompanyCreate(CompanyDetails):
    name: str = Field(min_length=1, max_length=255)
    eik: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    country: str = Field(default="BG", min_length=2, max_length=2)
    base_currency: str = Field(default="EUR", min_length=3, max_length=3)
    is_vat_registered: bool = False


class CompanyUpdate(CompanyDetails):
    """Частично обновяване на реквизитите (всички полета са по избор)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    eik: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    is_vat_registered: bool | None = None
    # Maker-checker: True/False задава политиката на дружеството. Не подадено поле
    # означава „не пипай“ (виж `exclude_unset` в service.update_company).
    maker_checker_enabled: bool | None = None


class CompanyOut(CompanyDetails):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    eik: str | None
    vat_number: str | None
    country: str
    base_currency: str
    is_vat_registered: bool
    is_active: bool
    # None = важи глобалната стойност (`MAKER_CHECKER_ENABLED`).
    maker_checker_enabled: bool | None = None


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
    role_id: uuid.UUID | None = None   # гъвкава роля от RBAC модула
    role_name: str | None = None


class MemberAdd(BaseModel):
    email: str = Field(max_length=255)
    role: CompanyRole


class MemberRoleUpdate(BaseModel):
    role: CompanyRole
