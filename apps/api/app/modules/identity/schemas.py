"""Pydantic схеми за Identity модула."""
import uuid
from typing import Literal

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


# ==================== Двуфакторна автентикация ====================
class MfaChallenge(BaseModel):
    """Отговорът на първата стъпка при включена 2FA.

    Нарочно **няма** `access_token`: клиент, който не знае за втората стъпка, не
    бива да помисли, че е влязъл. `mfa_required` е полето, по което и уеб, и
    мобилният клиент различават двата отговора на `/auth/login`.
    """

    mfa_required: Literal[True] = True
    mfa_token: str
    expires_in: int  # живот на междинния токен в секунди


class TwoFactorLoginRequest(BaseModel):
    mfa_token: str = Field(min_length=1, max_length=2048)
    # Приема и 6-цифрен TOTP код, и резервен код с тире — нормализира се в сървъра.
    code: str = Field(min_length=1, max_length=32)


class TotpStatus(BaseModel):
    enabled: bool
    #: Започнато, но непотвърдено включване — QR кодът е издаден, кодът още не е сверен.
    pending: bool = False
    recovery_codes_left: int = 0


class TotpSetup(BaseModel):
    """Данните за сканиране. Тайната се връща и като низ — за ръчно въвеждане."""

    secret: str
    otpauth_uri: str
    qr_svg: str


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class TotpRecoveryCodes(BaseModel):
    """Резервните кодове в чист вид — показват се ВЕДНЪЖ, при включването."""

    recovery_codes: list[str]


class TotpDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=32)
