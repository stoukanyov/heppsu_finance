"""Логика на таблото за кантора: преглед на всички клиенти и задачи по тях.

Заявките са **групови, не в цикъл**. Кантора с 60 клиента × 5 броения на клиент би
означавала 300 заявки на зареждане на екрана; тук са няколко `GROUP BY` заявки общо.
Изключение е изчисляването на срокове, което е чиста функция върху компанията и не
пипа базата за всеки клиент повече от веднъж.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounting.models import EntryStatus, JournalEntry
from app.modules.banking.models import BankTransaction, BankTxStatus
from app.modules.companies.models import Company, Membership
from app.modules.deadlines import service as deadlines_service
from app.modules.documents.models import Document, DocumentStatus
from app.modules.firm.models import FirmTask, TaskStatus
from app.modules.firm.schemas import (
    ClientOverviewOut,
    ClientTotalsOut,
    NextDeadlineOut,
    TaskCreate,
    TaskUpdate,
)
from app.modules.identity.models import User
from app.modules.vat.models import VatPeriodClosing

# Документ, който още чака човек. Осчетоводените и архивираните не влизат.
_DOCS_PENDING = (
    DocumentStatus.RECEIVED,
    DocumentStatus.OCR_PROCESSING,
    DocumentStatus.RECOGNIZED,
    DocumentStatus.NEEDS_REVIEW,
    DocumentStatus.MISSING_DATA,
    DocumentStatus.POTENTIAL_DUPLICATE,
    DocumentStatus.PROPOSED,
    DocumentStatus.RETURNED,
)
_BANK_PENDING = (BankTxStatus.UNMATCHED, BankTxStatus.PARTIALLY_MATCHED)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


# ==================================================================== достъп
def accessible_companies(db: Session, user: User) -> list[Company]:
    """Клиентите на потребителя = компаниите, в които има членство.

    Това е и правилото за достъп: няма отделен механизъм, който да се разсинхронизира
    с tenant скоупа на останалата система.
    """
    return list(
        db.scalars(
            select(Company)
            .join(Membership, Membership.company_id == Company.id)
            .where(Membership.user_id == user.id, Company.is_active.is_(True))
            .order_by(Company.name)
        )
    )


def _require_access(db: Session, user: User, company_id: uuid.UUID) -> Company:
    company = db.scalar(
        select(Company)
        .join(Membership, Membership.company_id == Company.id)
        .where(Membership.user_id == user.id, Company.id == company_id)
    )
    if company is None:
        raise _err("Нямате достъп до това дружество", status.HTTP_403_FORBIDDEN)
    return company


# ==================================================================== броения
def _count_by_company(db: Session, model, ids: list[uuid.UUID], *filters) -> dict[uuid.UUID, int]:
    """Едно `GROUP BY company_id` вместо по заявка на клиент."""
    if not ids:
        return {}
    rows = db.execute(
        select(model.company_id, func.count())
        .where(model.company_id.in_(ids), *filters)
        .group_by(model.company_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def client_overview(
    db: Session, user: User, *, reference_date: dt.date | None = None
) -> list[ClientOverviewOut]:
    """Състоянието на всеки клиент: какво чака работа и кой е следващият срок."""
    today = reference_date or dt.date.today()
    companies = accessible_companies(db, user)
    ids = [c.id for c in companies]

    docs = _count_by_company(db, Document, ids, Document.status.in_(_DOCS_PENDING))
    drafts = _count_by_company(db, JournalEntry, ids, JournalEntry.status == EntryStatus.DRAFT)
    bank = _count_by_company(db, BankTransaction, ids, BankTransaction.status.in_(_BANK_PENDING))
    tasks = _count_by_company(
        db, FirmTask, ids, FirmTask.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS))
    )
    overdue_tasks = _count_by_company(
        db,
        FirmTask,
        ids,
        FirmTask.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
        FirmTask.due_date.is_not(None),
        FirmTask.due_date < today,
    )

    # Последният приключен ДДС период на клиент — показва докъде е стигнало отчитането.
    closings: dict[uuid.UUID, dt.datetime] = {}
    if ids:
        rows = db.execute(
            select(VatPeriodClosing.company_id, func.max(VatPeriodClosing.created_at))
            .where(VatPeriodClosing.company_id.in_(ids))
            .group_by(VatPeriodClosing.company_id)
        ).all()
        closings = {row[0]: row[1] for row in rows}

    result: list[ClientOverviewOut] = []
    for company in companies:
        deadlines = deadlines_service.upcoming_deadlines(
            db, company, reference_date=today, days_ahead=90
        )
        next_deadline = None
        if deadlines:
            d = deadlines[0]
            next_deadline = NextDeadlineOut(
                key=d.key,
                title=d.title,
                due_date=d.due_date,
                days_remaining=d.days_remaining,
                authority=d.authority,
            )

        totals = ClientTotalsOut(
            pending_documents=docs.get(company.id, 0),
            draft_entries=drafts.get(company.id, 0),
            unreconciled_transactions=bank.get(company.id, 0),
            open_tasks=tasks.get(company.id, 0),
            overdue_tasks=overdue_tasks.get(company.id, 0),
        )
        result.append(
            ClientOverviewOut(
                company_id=company.id,
                name=company.name,
                eik=company.eik,
                is_vat_registered=company.is_vat_registered,
                last_vat_closing_at=closings.get(company.id),
                totals=totals,
                next_deadline=next_deadline,
                # „Чака работа“ е натрупано изоставане, а не наближаващ срок. Ако
                # смесим двете, при срок другата седмица светва целият списък и
                # маркерът престава да значи каквото и да е.
                needs_attention=totals.needs_attention,
                deadline_soon=bool(next_deadline and next_deadline.days_remaining <= 3),
            )
        )

    # Първо реалното изоставане, после наближаващите срокове, после по близост.
    result.sort(
        key=lambda c: (
            not c.needs_attention,
            not c.deadline_soon,
            c.next_deadline.days_remaining if c.next_deadline else 9999,
            c.name,
        )
    )
    return result


# ==================================================================== задачи
def list_tasks(
    db: Session,
    user: User,
    *,
    company_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    only_open: bool = False,
) -> list[FirmTask]:
    ids = [c.id for c in accessible_companies(db, user)]
    if not ids:
        return []
    stmt = select(FirmTask).where(FirmTask.company_id.in_(ids))
    if company_id is not None:
        stmt = stmt.where(FirmTask.company_id == company_id)
    if assignee_id is not None:
        stmt = stmt.where(FirmTask.assignee_id == assignee_id)
    if only_open:
        stmt = stmt.where(FirmTask.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))
    # Просрочените отгоре, после по срок; задачите без срок — накрая.
    return list(
        db.scalars(
            stmt.order_by(
                FirmTask.due_date.is_(None), FirmTask.due_date, FirmTask.created_at.desc()
            )
        )
    )


def create_task(db: Session, user: User, data: TaskCreate) -> FirmTask:
    _require_access(db, user, data.company_id)
    if data.assignee_id is not None:
        assignee_has_access = db.scalar(
            select(Membership.id).where(
                Membership.user_id == data.assignee_id, Membership.company_id == data.company_id
            )
        )
        if assignee_has_access is None:
            raise _err(
                "Изпълнителят няма достъп до това дружество — добави го в екипа му първо"
            )
    if data.deadline_key:
        existing = db.scalar(
            select(FirmTask.id).where(
                FirmTask.company_id == data.company_id,
                FirmTask.deadline_key == data.deadline_key,
                FirmTask.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
            )
        )
        if existing is not None:
            raise _err(
                "За този срок вече има отворена задача при клиента", status.HTTP_409_CONFLICT
            )

    task = FirmTask(created_by_id=user.id, **data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, user: User, task_id: uuid.UUID, data: TaskUpdate) -> FirmTask:
    task = db.get(FirmTask, task_id)
    if task is None:
        raise _err("Задачата не е намерена", status.HTTP_404_NOT_FOUND)
    _require_access(db, user, task.company_id)

    payload = data.model_dump(exclude_unset=True)
    if payload.get("status") == TaskStatus.DONE and task.status != TaskStatus.DONE:
        task.completed_at = dt.datetime.now(dt.UTC)
    elif "status" in payload and payload["status"] != TaskStatus.DONE:
        task.completed_at = None
    for key, value in payload.items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, user: User, task_id: uuid.UUID) -> None:
    task = db.get(FirmTask, task_id)
    if task is None:
        raise _err("Задачата не е намерена", status.HTTP_404_NOT_FOUND)
    _require_access(db, user, task.company_id)
    db.delete(task)
    db.commit()


# ==================================================================== групови действия
def vat_readiness(
    db: Session, user: User, period_code: str, company_ids: list[uuid.UUID] | None = None
) -> list[dict]:
    """Кои клиенти са готови за приключване на ДДС периода и кои не.

    **Съзнателно НЕ предлагаме групово приключване.** Приключването осчетоводява
    резултата и заключва периода; да се направи за десет клиента с един бутон, без
    някой да е видял числата, е точно грешката, която софтуерът трябва да предотврати,
    а не да улесни. Груповото действие тук е прегледът — самото приключване остава
    едно кликване при клиента, където се виждат сумите.
    """
    from app.modules.accounting.models import AccountingPeriod
    from app.modules.vat import service as vat_service

    companies = accessible_companies(db, user)
    if company_ids is not None:
        wanted = set(company_ids)
        companies = [c for c in companies if c.id in wanted]

    result: list[dict] = []
    for company in companies:
        period = db.scalar(
            select(AccountingPeriod).where(
                AccountingPeriod.company_id == company.id, AccountingPeriod.code == period_code
            )
        )
        if period is None:
            result.append({
                "company_id": company.id, "name": company.name, "ready": False,
                "period_id": None, "closed": False,
                "blockers": [f"Няма счетоводен период {period_code}"],
                "warnings": [],
            })
            continue

        closed = db.scalar(
            select(VatPeriodClosing.id).where(
                VatPeriodClosing.company_id == company.id, VatPeriodClosing.period_id == period.id
            )
        ) is not None
        controls = vat_service.vat_period_controls(db, company.id, period.id)
        blockers = [c.message for c in controls if c.level == "ERROR"]
        warnings = [c.message for c in controls if c.level != "ERROR"]
        if not company.is_vat_registered:
            blockers.append("Дружеството не е регистрирано по ЗДДС")

        result.append({
            "company_id": company.id, "name": company.name,
            "period_id": period.id, "closed": closed,
            "ready": not blockers and not closed,
            "blockers": blockers, "warnings": warnings,
        })
    return result


def bulk_nap_packages(
    db: Session, user: User, period_code: str, company_ids: list[uuid.UUID]
) -> tuple[bytes, list[dict]]:
    """Пакетите за НАП на няколко клиента в един ZIP, по папка на клиент.

    Свалянето е безопасно да е групово — то нищо не променя. Клиент, при който
    генерирането се спъва, не проваля целия архив: попада в отчета с причината.
    """
    import io
    import re
    import zipfile

    from app.modules.accounting.models import AccountingPeriod
    from app.modules.vat import service as vat_service

    accessible = {c.id: c for c in accessible_companies(db, user)}
    report: list[dict] = []
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for company_id in company_ids:
            company = accessible.get(company_id)
            if company is None:
                report.append({"company_id": company_id, "name": "—", "ok": False,
                               "reason": "Няма достъп до това дружество"})
                continue
            period = db.scalar(
                select(AccountingPeriod).where(
                    AccountingPeriod.company_id == company.id,
                    AccountingPeriod.code == period_code,
                )
            )
            if period is None:
                report.append({"company_id": company_id, "name": company.name, "ok": False,
                               "reason": f"Няма период {period_code}"})
                continue
            try:
                zip_bytes, filename = vat_service.build_nap_files(db, company.id, period.id)
            except HTTPException as exc:
                report.append({"company_id": company_id, "name": company.name, "ok": False,
                               "reason": str(exc.detail)})
                continue

            safe = re.sub(r"[^\w\-. ]", "_", company.name).strip() or str(company.id)
            archive.writestr(f"{safe}/{filename}", zip_bytes)
            report.append({"company_id": company_id, "name": company.name, "ok": True,
                           "reason": None, "filename": filename})

    return buf.getvalue(), report


def tasks_from_deadlines(
    db: Session, user: User, company_id: uuid.UUID, *, days_ahead: int = 30
) -> list[FirmTask]:
    """Създава задачи за предстоящите срокове на клиента, без да дублира съществуващи.

    Ръчното преписване на календара в задачи е точно работата, която софтуерът трябва
    да поеме. Идемпотентно: ключът на срока пази от повторно създаване.
    """
    company = _require_access(db, user, company_id)
    deadlines = deadlines_service.upcoming_deadlines(db, company, days_ahead=days_ahead)
    existing = set(
        db.scalars(
            select(FirmTask.deadline_key).where(
                FirmTask.company_id == company_id,
                FirmTask.deadline_key.is_not(None),
                FirmTask.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
            )
        )
    )
    created: list[FirmTask] = []
    for d in deadlines:
        if d.key in existing:
            continue
        task = FirmTask(
            company_id=company_id,
            title=d.title,
            description=d.description,
            due_date=d.due_date,
            deadline_key=d.key,
            created_by_id=user.id,
        )
        db.add(task)
        created.append(task)
    if created:
        db.commit()
        for task in created:
            db.refresh(task)
    return created
