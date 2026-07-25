"""API рутер за банковия модул (tenant-scoped)."""
import uuid

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.banking import service
from app.modules.banking.models import BankTxStatus
from app.modules.banking.schemas import (
    BankAccountCreate,
    BankAccountOut,
    BankConnectionOut,
    BankTransactionOut,
    ImportRequest,
    ImportResult,
    LinkAccountsIn,
    MatchOut,
    MatchRequest,
    MatchSuggestion,
    StartConnectionIn,
)

router = APIRouter(prefix="/banking", tags=["banking"])


# ---------- Банкови сметки ----------
@router.post("/accounts", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.view")])
def create_bank_account(data: BankAccountCreate, ctx: CurrentCompany, db: DbSession) -> BankAccountOut:
    return BankAccountOut.model_validate(service.create_bank_account(db, ctx.company.id, data))


@router.get("/accounts", response_model=list[BankAccountOut], dependencies=[require("banking.view")])
def list_bank_accounts(ctx: CurrentCompany, db: DbSession) -> list[BankAccountOut]:
    return [BankAccountOut.model_validate(a) for a in service.list_bank_accounts(db, ctx.company.id)]


@router.post("/accounts/{account_id}/import", response_model=ImportResult, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.import")])
def import_transactions(
    account_id: uuid.UUID, data: ImportRequest, ctx: CurrentCompany, db: DbSession
) -> ImportResult:
    return service.import_transactions(db, ctx.company, account_id, data.transactions)


@router.post("/accounts/{account_id}/import-csv", response_model=ImportResult, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.import")])
async def import_csv(
    account_id: uuid.UUID,
    ctx: CurrentCompany,
    db: DbSession,
    file: UploadFile = File(...),
    date_column: str = Form(...),
    amount_column: str = Form(...),
    reference_column: str | None = Form(None),
    description_column: str | None = Form(None),
    delimiter: str = Form(","),
    date_format: str = Form("%Y-%m-%d"),
    decimal_comma: bool = Form(False),
) -> ImportResult:
    """Импорт на банково извлечение от CSV със съпоставяне на колони."""
    content = await file.read()
    return service.import_csv(
        db, ctx.company, account_id, content,
        date_column, amount_column, reference_column, description_column,
        delimiter, date_format, decimal_comma,
    )


@router.post("/accounts/{account_id}/import-mt940", response_model=ImportResult, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.import")])
async def import_mt940(
    account_id: uuid.UUID, ctx: CurrentCompany, db: DbSession, file: UploadFile = File(...)
) -> ImportResult:
    """Импорт на банково извлечение във формат SWIFT MT940."""
    content = await file.read()
    return service.import_mt940(db, ctx.company, account_id, content)


@router.post("/accounts/{account_id}/import-camt", response_model=ImportResult, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.import")])
async def import_camt(
    account_id: uuid.UUID, ctx: CurrentCompany, db: DbSession, file: UploadFile = File(...)
) -> ImportResult:
    """Импорт на банково извлечение във формат ISO 20022 CAMT.053 (XML)."""
    content = await file.read()
    return service.import_camt(db, ctx.company, account_id, content)


# ---------- Движения ----------
@router.get("/transactions", response_model=list[BankTransactionOut], dependencies=[require("banking.view")])
def list_transactions(
    ctx: CurrentCompany,
    db: DbSession,
    bank_account_id: uuid.UUID | None = None,
    status: BankTxStatus | None = None,
) -> list[BankTransactionOut]:
    txs = service.list_transactions(db, ctx.company.id, bank_account_id=bank_account_id, status_filter=status)
    return [BankTransactionOut.model_validate(t) for t in txs]


@router.get("/transactions/{tx_id}", response_model=BankTransactionOut, dependencies=[require("banking.view")])
def get_transaction(tx_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> BankTransactionOut:
    return BankTransactionOut.model_validate(service.get_transaction(db, ctx.company.id, tx_id))


# ---------- Съгласуване ----------
@router.post("/transactions/{tx_id}/suggest-matches", response_model=list[MatchSuggestion], dependencies=[require("banking.reconcile")])
def suggest_matches(tx_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> list[MatchSuggestion]:
    return service.suggest_matches(db, ctx.company.id, tx_id)


@router.post("/transactions/{tx_id}/match", response_model=MatchOut, status_code=status.HTTP_201_CREATED, dependencies=[require("banking.reconcile")])
def match_transaction(
    tx_id: uuid.UUID, data: MatchRequest, ctx: CurrentCompany, db: DbSession
) -> MatchOut:
    match = service.create_match(
        db, ctx.company.id, tx_id, data.journal_entry_id, data.amount, ctx.membership.user_id
    )
    return MatchOut.model_validate(match)


@router.delete("/transactions/{tx_id}/matches/{match_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[require("banking.reconcile")])
def unmatch_transaction(
    tx_id: uuid.UUID, match_id: uuid.UUID, ctx: CurrentCompany, db: DbSession
) -> None:
    service.delete_match(db, ctx.company.id, tx_id, match_id)


@router.post("/transactions/{tx_id}/ignore", response_model=BankTransactionOut, dependencies=[require("banking.reconcile")])
def ignore_transaction(tx_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> BankTransactionOut:
    return BankTransactionOut.model_validate(service.ignore_transaction(db, ctx.company.id, tx_id))


# ---------------------------------------------------------------- open banking (PSD2)
@router.get("/providers", dependencies=[require("banking.view")])
def bank_providers() -> dict:
    """Кои доставчици на банкови данни са налични и кой се ползва."""
    return service.list_bank_providers()


@router.get("/institutions", dependencies=[require("banking.view")])
def institutions(
    ctx: CurrentCompany,
    country: str = Query(default="BG", min_length=2, max_length=2),
    provider: str | None = Query(default=None),
) -> list[dict]:
    """Банките, които доставчикът поддържа за държавата."""
    return service.list_institutions(country, provider)


@router.post("/connections", response_model=BankConnectionOut,
             status_code=status.HTTP_201_CREATED, dependencies=[require("banking.import")])
def start_connection(
    data: StartConnectionIn, ctx: CurrentCompany, db: DbSession
) -> BankConnectionOut:
    """Започва съгласие по PSD2 — връща линк за удостоверяване пред банката."""
    connection = service.start_connection(
        db, ctx.company, data.institution_id, str(data.redirect_url),
        ctx.membership.user_id, data.provider,
    )
    return BankConnectionOut.model_validate(connection)


@router.get("/connections", response_model=list[BankConnectionOut],
            dependencies=[require("banking.view")])
def list_connections(ctx: CurrentCompany, db: DbSession) -> list[BankConnectionOut]:
    return [
        BankConnectionOut.model_validate(c) for c in service.list_connections(db, ctx.company.id)
    ]


@router.get("/connections/{connection_id}/remote-accounts", dependencies=[require("banking.view")])
def remote_accounts(connection_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> list[dict]:
    """Сметките, до които съгласието дава достъп — за да се свържат с местните."""
    return service.remote_accounts(db, ctx.company.id, connection_id)


@router.post("/connections/{connection_id}/link-accounts", dependencies=[require("banking.import")])
def link_accounts(
    connection_id: uuid.UUID, data: LinkAccountsIn, ctx: CurrentCompany, db: DbSession
) -> dict:
    links = service.link_accounts(db, ctx.company, connection_id, data.mapping)
    return {"linked": len(links)}


@router.post("/connections/{connection_id}/sync", dependencies=[require("banking.import")])
def sync_connection(
    connection_id: uuid.UUID, ctx: CurrentCompany, db: DbSession,
    days_back: int = Query(default=30, ge=1, le=730),
) -> dict:
    """Изтегля движенията и ги внася през същия път като файловия импорт."""
    return service.sync_connection(db, ctx.company, connection_id, days_back)


@router.get("/consent-warnings", dependencies=[require("banking.view")])
def consent_warnings(ctx: CurrentCompany, db: DbSession) -> list[dict]:
    """Съгласия, които изтичат скоро или вече са изтекли."""
    return service.consent_warnings(db, ctx.company.id)
