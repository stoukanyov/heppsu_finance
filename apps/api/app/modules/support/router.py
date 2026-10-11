"""API за докладване: дефект, инцидент, предложение за подобрение.

    POST /support/report  — само за влязъл потребител; записва и опитва да препрати
    GET  /support/config  — публично, само за четене: настроено ли е препращането

`config` е без вход нарочно: Definition of Done (`infra/dod.yml`, точка 1) го
пита от `infra/deploy.sh` с голо `curl`, за да откаже production деплой, ако
функцията е в кода, но не е включена в средата. Отговорът е едно булево —
нито адресът, нито токенът излизат.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import RateLimitRule, ThrottlePolicy, make_throttle_dependency
from app.modules.companies.models import Membership
from app.modules.support import forwarder
from app.modules.support.models import STATUS_PENDING, STATUS_SENT, SupportReport
from app.modules.support.schemas import SupportConfigOut, SupportReportIn, SupportReportOut

router = APIRouter(prefix="/support", tags=["support"])


def _report_rule() -> RateLimitRule:
    return RateLimitRule(
        max_attempts=settings.SUPPORT_REPORT_RATE_LIMIT,
        window_seconds=settings.SUPPORT_REPORT_RATE_WINDOW_SECONDS,
    )


# По потребител (от всеки адрес) и по двойката потребител+адрес. Входът вече е
# зад автентикация — таванът пази опашката и Control Center от зациклил клиент,
# не от анонимен наплив.
ReportThrottle = make_throttle_dependency(
    "support-report", lambda: ThrottlePolicy(pair=_report_rule(), subject=_report_rule())
)


@router.get("/config", response_model=SupportConfigOut)
def support_config() -> SupportConfigOut:
    """Настроено ли е препращането към Control Center в тази среда (адрес + токен)."""
    return SupportConfigOut(configured=settings.support_forwarding_configured)


@router.post("/report", response_model=SupportReportOut, status_code=status.HTTP_201_CREATED)
def submit_report(
    data: SupportReportIn,
    db: DbSession,
    user: CurrentUser,
    guard: ReportThrottle,
    x_company_id: Annotated[uuid.UUID | None, Header(alias="X-Company-Id")] = None,
) -> SupportReportOut:
    """Записва доклада и веднага опитва да го препрати.

    201 значи „записан при нас“. Дали е стигнал до поддръжката, казва
    `forwarded`: при `false` докладът чака в опашката и фоновият цикъл ще го
    препрати — клиентът казва „приехме го, ще бъде препратен“, не „изпратено“.
    """
    subject_key = str(user.id)
    guard.check(
        subject_key,
        detail="Твърде много доклада за кратко време. Опитайте отново след малко.",
    )
    guard.register_event(subject_key)

    # Дружеството се закача само ако потребителят е член — иначе всеки може да
    # припише доклада си на чужд клиент. Липсващо или чуждо → без дружество,
    # не отказ: докладът е по-важен от контекста му.
    company_id = None
    if x_company_id is not None:
        is_member = db.scalar(
            select(Membership.id).where(
                Membership.user_id == user.id, Membership.company_id == x_company_id
            )
        )
        company_id = x_company_id if is_member else None

    report = SupportReport(
        user_id=user.id,
        company_id=company_id,
        category=data.category,
        subject=data.subject,
        message=data.message,
        page=(data.page or "").strip() or None,
        submitter_ip=guard.ip if guard.ip and guard.ip != "unknown" else None,
        forward_status=STATUS_PENDING,
        attempts=0,
    )
    db.add(report)
    db.commit()
    report_id = report.id

    forwarder.forward_one(db, report_id)

    fresh = db.get(SupportReport, report_id)
    db.refresh(fresh)
    return SupportReportOut(
        id=fresh.id,
        forwarded=fresh.forward_status == STATUS_SENT,
        status=fresh.forward_status,
        reference=fresh.reference,
    )
