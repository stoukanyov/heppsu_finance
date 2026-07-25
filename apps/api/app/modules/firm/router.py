"""API рутер за таблото на счетоводната кантора.

За разлика от останалите модули тук **няма** `X-Company-Id`: екранът е нарочно
над отделния клиент. Достъпът се определя от членствата на потребителя — вижда
точно тези клиенти, до които така или иначе има достъп.
"""
import datetime as dt
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.modules.firm import service
from app.modules.firm.schemas import (
    BulkPackagesRequest,
    ClientOverviewOut,
    GenerateTasksRequest,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(prefix="/firm", tags=["firm"])


@router.get("/clients", response_model=list[ClientOverviewOut])
def list_clients(
    user: CurrentUser,
    db: DbSession,
    reference_date: dt.date | None = Query(
        None, description="Отправна дата (по подразбиране днес) — прави отговора детерминиран."
    ),
) -> list[ClientOverviewOut]:
    """Всички клиенти с това, което чака работа, и следващия им срок."""
    return service.client_overview(db, user, reference_date=reference_date)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    user: CurrentUser,
    db: DbSession,
    company_id: uuid.UUID | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    only_open: bool = Query(default=False),
) -> list[TaskOut]:
    return [
        TaskOut.model_validate(t)
        for t in service.list_tasks(
            db, user, company_id=company_id, assignee_id=assignee_id, only_open=only_open
        )
    ]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(data: TaskCreate, user: CurrentUser, db: DbSession) -> TaskOut:
    return TaskOut.model_validate(service.create_task(db, user, data))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID, data: TaskUpdate, user: CurrentUser, db: DbSession
) -> TaskOut:
    return TaskOut.model_validate(service.update_task(db, user, task_id, data))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    service.delete_task(db, user, task_id)


@router.get("/bulk/vat-readiness")
def vat_readiness(
    user: CurrentUser,
    db: DbSession,
    period_code: str = Query(description='Код на периода, напр. "2026-03"'),
) -> dict:
    """Кои клиенти са готови за приключване на ДДС периода — групов преглед.

    Груповото *приключване* нарочно липсва: то осчетоводява и заключва период, а това
    не бива да се случва за десет клиента наведнъж, без някой да е видял числата.
    """
    rows = service.vat_readiness(db, user, period_code)
    return {
        "period_code": period_code,
        "ready": sum(1 for r in rows if r["ready"]),
        "closed": sum(1 for r in rows if r["closed"]),
        "blocked": sum(1 for r in rows if not r["ready"] and not r["closed"]),
        "clients": rows,
        "note": (
            "Приключването остава по клиент — на екрана на клиента, където се виждат "
            "сумите. Тук се вижда само кой е готов."
        ),
    }


@router.post("/bulk/nap-packages")
def bulk_nap_packages(
    data: BulkPackagesRequest, user: CurrentUser, db: DbSession
) -> Response:
    """Пакетите за НАП на избрани клиенти в един ZIP, по папка на клиент."""
    content, report = service.bulk_nap_packages(db, user, data.period_code, data.company_ids)
    ok = sum(1 for r in report if r["ok"])
    filename = f"NAP-{data.period_code.replace('-', '')}-{ok}-klienta.zip"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        # Отчетът е ASCII-safe: само броячи. Причините за пропуснатите клиенти се
        # четат от `GET /firm/bulk/vat-readiness`.
        "X-Packages-Included": str(ok),
        "X-Packages-Skipped": str(len(report) - ok),
    }
    return Response(content=content, media_type="application/zip", headers=headers)


@router.post("/tasks/from-deadlines", response_model=list[TaskOut], status_code=status.HTTP_201_CREATED)
def generate_tasks(data: GenerateTasksRequest, user: CurrentUser, db: DbSession) -> list[TaskOut]:
    """Създава задачи за предстоящите срокове на клиента. Идемпотентно."""
    return [
        TaskOut.model_validate(t)
        for t in service.tasks_from_deadlines(
            db, user, data.company_id, days_ahead=data.days_ahead
        )
    ]
