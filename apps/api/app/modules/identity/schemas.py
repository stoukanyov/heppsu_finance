"""Pydantic схеми за Identity модула."""
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    """Двойката токени. Формата е фиксирана — мобилният клиент чете точно тези имена.

    `access_token` умишлено остава с непроменени име и семантика: уеб приложението и
    съществуващите тестове разчитат на него.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # живот на access токена в секунди


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)
    # По подразбиране излизаме само от текущото устройство.
    all_devices: bool = False
