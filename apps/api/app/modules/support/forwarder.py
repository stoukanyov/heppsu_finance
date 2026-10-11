"""Препращане на докладите към Control Center — опашка с повторение.

Договорът е кодът на Control Center (`app/api/tickets.py`, `submit`):

    POST {COCKPIT_URL}/api/tickets
    X-App-Token:    токенът на системата (`aifos` / `aifos-preprod`)
    X-Submitter-IP: адресът на крайния подател (системата трябва да е в
                    COCKPIT_TICKET_PROXY_SYSTEMS, иначе заглавката се пренебрегва)
    тяло:           TicketIn {category, title (3..200), body (1..4000), contact?}
    отговор:        201 {"reference": "T-000123", "status": "new"}

Как се държи всеки отговор:

* 2xx — тикетът е отворен. Записваме номера и редът НИКОГА не се праща пак.
  Control Center няма ключ за идемпотентност, затова „изпратен ли е“ се пази
  тук: статус `sent` + номер.
* 400 / 422 — Control Center отказва самото съдържание. Повторението ще даде
  същото; редът става `rejected` и остава в базата за човек.
* 429, 5xx, 401/403/404, мрежа, изтекло време — опитва се пак, с изчакване
  1, 2, 4… минути до `SUPPORT_FORWARD_MAX_BACKOFF_SECONDS` (и не по-рано от
  `Retry-After`, ако Control Center го е казал). 401/404 са грешна настройка —
  щом се поправи, чакащите тръгват сами.

Остатъчен риск, назован: ако Control Center отвори тикета, а отговорът се
изгуби по пътя (прекъсната връзка след изпращането), не знаем, че е отворен, и
пращаме пак — два тикета вместо нула. Тялото носи номера на доклада ни
(„AIFOS доклад: <id>“), за да се вижда при триажа, че са едно и също.
Пълното решение е ключ за идемпотентност в Control Center.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.companies.models import Company
from app.modules.identity.models import User
from app.modules.support.models import (
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_SENT,
    SupportReport,
)

logger = logging.getLogger("app.support")

COCKPIT_TICKETS_PATH = "/api/tickets"

#: Таваните на `TicketIn` в Control Center (sha в tests/test_support.py).
TICKET_TITLE_MAX = 200
TICKET_BODY_MAX = 4000
TICKET_CONTACT_MAX = 320

#: Отговори, при които повторението няма смисъл: съдържанието е отказано.
_PERMANENT_STATUSES = frozenset({400, 422})

#: Колко дълго редът е „зает“ от процеса, който го праща. По-дълго от времето
#: за един опит, за да не го вземе втори процес по средата.
_CLAIM_EXTRA_SECONDS = 60

#: Долна граница на интервала на цикъла — грешна настройка (0) не бива да
#: превърне цикъла в непрекъснато питане на базата.
_MIN_INTERVAL_SECONDS = 5

#: Тестовете подменят транспорта (httpx.MockTransport) — навън не излиза нищо.
_transport: httpx.BaseTransport | None = None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_ticket(
    report: SupportReport,
    *,
    contact: str | None,
    company_name: str | None,
    environment: str,
) -> dict:
    """Тялото за `POST /api/tickets` — точно по `TicketIn`, нищо повече.

    Контекстът (екран, дружество, среда, номер на доклада) отива в края на
    текста: Control Center няма отделни полета за него, а при триажа трябва.
    """
    context = [f"AIFOS доклад: {report.id}", f"Среда: {environment}"]
    if report.page:
        context.insert(0, f"Екран: {report.page}")
    if company_name:
        context.insert(1 if report.page else 0, f"Дружество: {company_name}")
    footer = "\n\n—\n" + "\n".join(context)
    body = _clip(report.message, TICKET_BODY_MAX - len(footer)) + footer
    ticket: dict = {
        "category": report.category,
        "title": _clip(report.subject, TICKET_TITLE_MAX),
        "body": body,
    }
    if contact:
        ticket["contact"] = _clip(contact, TICKET_CONTACT_MAX)
    return ticket


def _headers(report: SupportReport) -> dict[str, str]:
    headers = {"X-App-Token": settings.COCKPIT_APP_TOKEN.strip()}
    if report.submitter_ip:
        headers["X-Submitter-IP"] = report.submitter_ip
    return headers


def _tickets_url() -> str:
    return settings.COCKPIT_URL.strip().rstrip("/") + COCKPIT_TICKETS_PATH


def _backoff_seconds(attempts: int, retry_after: str | None) -> int:
    wait = min(60 * 2 ** max(attempts - 1, 0), settings.SUPPORT_FORWARD_MAX_BACKOFF_SECONDS)
    if retry_after and retry_after.strip().isdigit():
        wait = max(wait, min(int(retry_after), settings.SUPPORT_FORWARD_MAX_BACKOFF_SECONDS))
    return wait


def _claim(db: Session, report_id: uuid.UUID, now: dt.datetime) -> bool:
    """Атомарно заема реда за този процес. False → някой друг го праща или вече е пратен."""
    lease = now + dt.timedelta(
        seconds=settings.SUPPORT_FORWARD_TIMEOUT_SECONDS + _CLAIM_EXTRA_SECONDS
    )
    result = db.execute(
        update(SupportReport)
        .where(
            SupportReport.id == report_id,
            SupportReport.forward_status == STATUS_PENDING,
            or_(SupportReport.claimed_until.is_(None), SupportReport.claimed_until < now),
        )
        .values(claimed_until=lease)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _record_failure(
    report: SupportReport, now: dt.datetime, error: str, *, retry_after: str | None = None, permanent: bool = False
) -> None:
    report.last_error = _clip(error, 500)
    report.claimed_until = None
    if permanent:
        report.forward_status = STATUS_REJECTED
        report.next_attempt_at = None
    else:
        report.next_attempt_at = now + dt.timedelta(seconds=_backoff_seconds(report.attempts, retry_after))


def forward_one(db: Session, report_id: uuid.UUID) -> SupportReport | None:
    """Един опит за един доклад. Връща реда след опита, или None, ако не е наш ред.

    Никога не хвърля заради Control Center — провалът е запис в реда, не 500
    към потребителя, който току-що ни е писал.
    """
    if not settings.support_forwarding_configured:
        return None
    now = _utcnow()
    if not _claim(db, report_id, now):
        return None

    report = db.get(SupportReport, report_id)
    if report is None:  # изтрит между заемането и четенето
        return None
    db.refresh(report)

    user = db.get(User, report.user_id) if report.user_id else None
    company = db.get(Company, report.company_id) if report.company_id else None
    ticket = build_ticket(
        report,
        contact=user.email if user else None,
        company_name=company.name if company else None,
        environment=settings.ENVIRONMENT,
    )

    report.attempts += 1
    report.last_attempt_at = now
    try:
        with httpx.Client(
            transport=_transport, timeout=settings.SUPPORT_FORWARD_TIMEOUT_SECONDS
        ) as client:
            response = client.post(_tickets_url(), json=ticket, headers=_headers(report))
    except httpx.HTTPError as exc:
        # Само типът: съобщението на httpx може да носи адреса, а логът и
        # колоната нямат нужда от него. Токенът е в заглавка и не стига дотук.
        _record_failure(report, now, f"мрежа: {type(exc).__name__}")
        db.commit()
        logger.warning("доклад %s: Control Center недостъпен (%s), опит %s",
                       report.id, type(exc).__name__, report.attempts)
        return report

    if response.is_success:
        reference = None
        try:
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("reference"), str):
                reference = payload["reference"][:32]
        except ValueError:
            pass
        report.forward_status = STATUS_SENT
        report.reference = reference
        report.sent_at = now
        report.next_attempt_at = None
        report.claimed_until = None
        # 2xx без номер: тикетът е отворен (не пращаме пак), но казваме, че номер няма.
        report.last_error = None if reference else f"HTTP {response.status_code} без номер на тикет"
        db.commit()
        logger.info("доклад %s → тикет %s", report.id, reference or "(без номер)")
        return report

    detail = _clip(response.text.strip().replace("\n", " "), 200)
    _record_failure(
        report,
        now,
        f"HTTP {response.status_code}: {detail}",
        retry_after=response.headers.get("retry-after"),
        permanent=response.status_code in _PERMANENT_STATUSES,
    )
    db.commit()
    logger.warning("доклад %s: Control Center върна %s, опит %s",
                   report.id, response.status_code, report.attempts)
    return report


def forward_due(session_factory: Callable[[], Session] = SessionLocal, *, limit: int = 20) -> int:
    """Праща чакащите доклади, чийто ред е дошъл. Връща колко са станали `sent`."""
    if not settings.support_forwarding_configured:
        return 0
    sent = 0
    with session_factory() as db:
        now = _utcnow()
        due_ids = db.scalars(
            select(SupportReport.id)
            .where(
                SupportReport.forward_status == STATUS_PENDING,
                or_(SupportReport.next_attempt_at.is_(None), SupportReport.next_attempt_at <= now),
                or_(SupportReport.claimed_until.is_(None), SupportReport.claimed_until < now),
            )
            .order_by(SupportReport.created_at)
            .limit(limit)
        ).all()
        for report_id in due_ids:
            report = forward_one(db, report_id)
            if report is not None and report.forward_status == STATUS_SENT:
                sent += 1
    return sent


async def run_forwarder_loop(stop: asyncio.Event) -> None:
    """Фоновият цикъл, пуснат при старт на приложението (`main.lifespan`).

    Работи във всеки uvicorn работник; заемането на реда (`_claim`) пази от
    двойно пращане. Грешка в един оборот не спира цикъла.
    """
    interval = max(settings.SUPPORT_FORWARD_INTERVAL_SECONDS, _MIN_INTERVAL_SECONDS)
    while not stop.is_set():
        try:
            await asyncio.to_thread(forward_due)
        except Exception:  # noqa: BLE001 — един лош оборот не бива да спре опашката
            logger.exception("препращането на докладите не мина в този оборот")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
