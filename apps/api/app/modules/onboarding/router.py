"""API рутер за въвеждане на клиент: настройка, начални салда, миграция, здраве на данните.

Модулът няма собствени таблици — работи върху съществуващите. Затова няма и `models.py`.
"""
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import CurrentCompany, DbSession, require
from app.core.clock import business_today
from app.modules.counterparties.models import CounterpartyType
from app.modules.onboarding import service
from app.modules.onboarding.schemas import (
    OpeningBalancesIn,
    OpeningBalancesPreviewOut,
    PostedEntryOut,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

MAX_UPLOAD = 5 * 1024 * 1024   # 5 MB стигат и за най-големия износ на контрагенти


def _read_upload(file: UploadFile) -> bytes:
    """Чете качения файл с таван — четем един байт над лимита, за да го засечем."""
    content = file.file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файлът е над 5 MB"
        )
    return content


@router.get("/status", dependencies=[require("company.view")])
def setup_status(ctx: CurrentCompany, db: DbSession) -> dict:
    """Какво още липсва, за да може да се работи с този клиент."""
    return service.setup_status(db, ctx.company)


@router.get("/health", dependencies=[require("reports.view")])
def health_check(ctx: CurrentCompany, db: DbSession) -> dict:
    """Проверка на данните — преди да се твърди, че месецът е приключен."""
    return service.health_check(db, ctx.company)


# ---------------------------------------------------------------- начални салда
@router.post("/opening-balances/preview", response_model=OpeningBalancesPreviewOut,
             dependencies=[require("accounting.view")])
def preview_opening(
    data: OpeningBalancesIn, ctx: CurrentCompany, db: DbSession
) -> OpeningBalancesPreviewOut:
    """Проверява салдата, без да записва: съществуват ли сметките и излиза ли балансът."""
    result = service.preview_opening_balances(db, ctx.company, [r.model_dump() for r in data.rows])
    return OpeningBalancesPreviewOut(**result)


@router.post("/opening-balances", response_model=PostedEntryOut,
             dependencies=[require("accounting.post_entry")])
def post_opening(data: OpeningBalancesIn, ctx: CurrentCompany, db: DbSession) -> PostedEntryOut:
    """Осчетоводява началните салда в дневник „Начални салда“."""
    entry = service.post_opening_balances(
        db, ctx.company, ctx.membership.user_id,
        data.on_date or business_today(), [r.model_dump() for r in data.rows],
    )
    return PostedEntryOut(
        id=entry.id, entry_number=entry.entry_number, document_date=entry.document_date
    )


@router.post("/opening-balances/parse-csv", response_model=OpeningBalancesPreviewOut,
             dependencies=[require("accounting.view")])
def parse_opening_csv(
    ctx: CurrentCompany,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    delimiter: Annotated[str, Form()] = ";",
    decimal_comma: Annotated[bool, Form()] = True,
) -> OpeningBalancesPreviewOut:
    """Чете оборотна ведомост от CSV и веднага я проверява."""
    content = _read_upload(file)
    rows = service.parse_opening_csv(content, delimiter, decimal_comma)
    return OpeningBalancesPreviewOut(**service.preview_opening_balances(db, ctx.company, rows))


# ---------------------------------------------------------------- миграция
@router.post("/counterparties/import-csv", dependencies=[require("counterparties.manage")])
def import_counterparties(
    ctx: CurrentCompany,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    name_column: Annotated[str, Form()],
    eik_column: Annotated[str | None, Form()] = None,
    vat_column: Annotated[str | None, Form()] = None,
    address_column: Annotated[str | None, Form()] = None,
    type_value: Annotated[CounterpartyType, Form()] = CounterpartyType.BOTH,
    delimiter: Annotated[str, Form()] = ";",
) -> dict:
    """Импорт на контрагенти от износ на друга счетоводна система (CSV, съпоставяне на колони)."""
    content = _read_upload(file)
    return service.import_counterparties_csv(
        db, ctx.company, content,
        name_column=name_column, eik_column=eik_column, vat_column=vat_column,
        address_column=address_column, type_value=type_value, delimiter=delimiter,
    )
