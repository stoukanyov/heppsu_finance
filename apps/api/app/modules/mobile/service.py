"""Логика на мобилния модул: сравнение на версии и приемане на сривове."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.mobile.models import CrashReport
from app.modules.mobile.schemas import (
    PLATFORM_ANDROID,
    PLATFORM_IOS,
    CrashGroup,
    CrashReportIn,
    ReleasePolicy,
)

# ----------------------------------------------------------------- версии

_VERSION_RE = re.compile(r"\d+")


def parse_version(raw: str | None) -> tuple[int, ...]:
    """„1.4.12+87“ → (1, 4, 12). Прочита толкова числа, колкото намери.

    Номерът на билда след „+“ съзнателно се отрязва: той расте при всяко
    компилиране и не носи информация за съвместимост. Незнаен или счупен низ
    дава (0,) — тоест „много стар“, което е безопасната посока: клиент, който
    не може да обяви версията си, се третира като остарял, не като най-нов.
    """
    if not raw:
        return (0,)
    head = raw.split("+", 1)[0]
    parts = tuple(int(n) for n in _VERSION_RE.findall(head)[:4])
    return parts or (0,)


def _compare(left: str | None, right: str | None) -> int:
    """-1 / 0 / 1 — с изравняване на дължината, за да е „1.4“ == „1.4.0“."""
    a, b = parse_version(left), parse_version(right)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def store_url(platform: str) -> str | None:
    if platform == PLATFORM_IOS:
        return settings.MOBILE_IOS_STORE_URL or None
    if platform == PLATFORM_ANDROID:
        return settings.MOBILE_ANDROID_STORE_URL or None
    return None


def release_policy(platform: str, version: str | None) -> ReleasePolicy:
    minimum = settings.MOBILE_MIN_SUPPORTED_VERSION or "0.0.0"
    latest = settings.MOBILE_LATEST_VERSION or None

    required = _compare(version, minimum) < 0
    # „Има по-нова“ се смята само ако версията е обявена — иначе всеки клиент
    # без настроена MOBILE_LATEST_VERSION би виждал покана към нищото.
    available = bool(latest) and _compare(version, latest) < 0

    return ReleasePolicy(
        update_required=required,
        update_available=available and not required,
        min_supported_version=minimum,
        latest_version=latest,
        store_url=store_url(platform),
        message=settings.MOBILE_UPDATE_MESSAGE or None,
    )


# ------------------------------------------------------------- изчистване

# Втора линия след изчистването в клиента. Нарочно е груба: по-добре нечетим
# доклад, отколкото ЕГН в базата с логовете.
_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<имейл>"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+"), "<токен>"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "<IBAN>"),
    # ЕГН (10), БУЛСТАТ (9/13), номера на карти. Суми не се пипат — те са до 8 цифри
    # и са нужни за възпроизвеждане на грешката.
    (re.compile(r"\b\d{9,16}\b"), "<номер>"),
)


def scrub(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------- отпечатък

# Всичко променливо между два еднакви срива: адреси в паметта, идентификатори,
# числа. Остава формата на грешката.
_NOISE = (
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\d+"),
)
_FRAMES_IN_FINGERPRINT = 5


def fingerprint(message: str, stack_trace: str | None) -> str:
    """Групиращ ключ: нормализирано съобщение + първите няколко кадъра от стека.

    Само съобщението не стига (една и съща формулировка идва от различни места),
    а целият стек не става за групиране — долните кадри се разминават между
    версии и устройства.
    """
    normalized = message
    for pattern in _NOISE:
        normalized = pattern.sub("#", normalized)

    frames = ""
    if stack_trace:
        head = [ln.strip() for ln in stack_trace.splitlines() if ln.strip()][:_FRAMES_IN_FINGERPRINT]
        frames = "\n".join(head)
        for pattern in _NOISE:
            frames = pattern.sub("#", frames)

    return hashlib.sha256(f"{normalized}\n---\n{frames}".encode()).hexdigest()


# --------------------------------------------------------------- записване


def record_crash(
    db: Session,
    data: CrashReportIn,
    *,
    company_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> CrashReport:
    message = scrub(data.message) or "(празно)"
    stack = scrub(data.stack_trace)

    report = CrashReport(
        company_id=company_id,
        user_id=user_id,
        platform=data.platform,
        app_version=data.app_version,
        build_number=data.build_number,
        os_version=data.os_version,
        device_model=data.device_model,
        kind=data.kind,
        message=message,
        stack_trace=stack,
        occurred_at=data.occurred_at,
        fingerprint=fingerprint(message, stack),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def list_groups(db: Session, *, limit: int = 50) -> list[CrashGroup]:
    """Сривовете, обединени по отпечатък, най-скорошните отгоре.

    Групирането е в Python, а не в SQL: заявката трябва да върне и последното
    съобщение, и списъка версии, а това в преносим SQL става с няколко обхода.
    При обеми, които го налагат, се сменя с агрегираща заявка.
    """
    rows = db.scalars(
        select(CrashReport).order_by(CrashReport.occurred_at.desc()).limit(2000)
    ).all()

    groups: dict[str, CrashGroup] = {}
    for row in rows:
        group = groups.get(row.fingerprint)
        if group is None:
            groups[row.fingerprint] = CrashGroup(
                fingerprint=row.fingerprint,
                message=row.message,
                count=1,
                first_seen=row.occurred_at,
                last_seen=row.occurred_at,
                versions=[row.app_version],
            )
            continue
        group.count += 1
        group.first_seen = min(group.first_seen, row.occurred_at)
        group.last_seen = max(group.last_seen, row.occurred_at)
        if row.app_version not in group.versions:
            group.versions.append(row.app_version)

    return sorted(groups.values(), key=lambda g: g.last_seen, reverse=True)[:limit]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
