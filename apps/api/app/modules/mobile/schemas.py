"""Pydantic схеми за мобилния модул."""
from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

# Платформи, които клиентът може да обяви. Свободен низ тук би напълнил базата
# с боклук при печатна грешка.
PLATFORM_IOS = "ios"
PLATFORM_ANDROID = "android"
PLATFORMS = (PLATFORM_IOS, PLATFORM_ANDROID)


class ReleasePolicy(BaseModel):
    """Отговор на въпроса „може ли тази версия да работи“.

    Решението се взема на сървъра, а не в клиента: така изваждането от употреба
    на дефектна версия не изисква ново издание в магазина.
    """

    update_required: bool          # блокиращо — под минимално поддържаната версия
    update_available: bool         # има по-нова, но текущата още работи
    min_supported_version: str
    latest_version: str | None
    store_url: str | None
    message: str | None            # защо е нужно обновяването (показва се на потребителя)


class CrashReportIn(BaseModel):
    platform: str = Field(max_length=20)
    app_version: str = Field(min_length=1, max_length=40)
    build_number: str | None = Field(default=None, max_length=40)
    os_version: str | None = Field(default=None, max_length=60)
    device_model: str | None = Field(default=None, max_length=80)
    kind: str = Field(default="DART", max_length=20)
    # Таваните са и защита: без тях един цикъл в клиента може да напълни диска.
    message: str = Field(min_length=1, max_length=2000)
    stack_trace: str | None = Field(default=None, max_length=20000)
    occurred_at: dt.datetime


class CrashReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    app_version: str
    build_number: str | None
    os_version: str | None
    device_model: str | None
    kind: str
    message: str
    stack_trace: str | None
    occurred_at: dt.datetime
    fingerprint: str
    created_at: dt.datetime


class CrashGroup(BaseModel):
    """Обобщение по дефект — това, което се гледа при триаж."""

    fingerprint: str
    message: str
    count: int
    first_seen: dt.datetime
    last_seen: dt.datetime
    versions: list[str]
