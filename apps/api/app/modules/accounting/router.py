"""API рутер за счетоводното ядро (tenant-scoped чрез X-Company-Id)."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.accounting import service
from app.modules.accounting.schemas import (
    AccountCreate,
    AccountOut,
    FiscalYearCreate,
    FiscalYearOut,
    JournalEntryCreate,
    JournalEntryOut,
    PeriodOut,
    PeriodStatusUpdate,
)

router = APIRouter(prefix="/accounting", tags=["accounting"])


# ---------- Сметкоплан ----------
@router.post("/chart/seed", response_model=list[AccountOut], status_code=status.HTTP_201_CREATED, dependencies=[require("accounting.manage_chart")])
def seed_chart(ctx: CurrentCompany, db: DbSession) -> list[AccountOut]:
    service.seed_standard_chart(db, ctx.company.id)
    return [AccountOut.model_validate(a) for a in service.list_accounts(db, ctx.company.id)]


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED, dependencies=[require("accounting.manage_chart")])
def create_account(data: AccountCreate, ctx: CurrentCompany, db: DbSession) -> AccountOut:
    account = service.create_account(db, ctx.company.id, data)
    return AccountOut.model_validate(account)


@router.get("/accounts", response_model=list[AccountOut], dependencies=[require("accounting.view")])
def list_accounts(ctx: CurrentCompany, db: DbSession) -> list[AccountOut]:
    return [AccountOut.model_validate(a) for a in service.list_accounts(db, ctx.company.id)]


# ---------- Периоди ----------
@router.post("/fiscal-years", response_model=FiscalYearOut, status_code=status.HTTP_201_CREATED, dependencies=[require("accounting.manage_chart")])
def create_fiscal_year(data: FiscalYearCreate, ctx: CurrentCompany, db: DbSession) -> FiscalYearOut:
    fy = service.create_fiscal_year(db, ctx.company.id, data)
    return FiscalYearOut.model_validate(fy)


@router.get("/fiscal-years", response_model=list[FiscalYearOut], dependencies=[require("accounting.view")])
def list_fiscal_years(ctx: CurrentCompany, db: DbSession) -> list[FiscalYearOut]:
    return [FiscalYearOut.model_validate(fy) for fy in service.list_fiscal_years(db, ctx.company.id)]


@router.patch("/periods/{period_id}/status", response_model=PeriodOut, dependencies=[require("accounting.close_period")])
def update_period_status(
    period_id: uuid.UUID, data: PeriodStatusUpdate, ctx: CurrentCompany, db: DbSession
) -> PeriodOut:
    period = service.set_period_status(db, ctx.company.id, period_id, data.status)
    return PeriodOut.model_validate(period)


# ---------- Счетоводни операции ----------
@router.post("/journal-entries", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    data: JournalEntryCreate, ctx: CurrentCompany, db: DbSession
) -> JournalEntryOut:
    entry = service.create_entry(db, ctx.company, ctx.membership.user_id, data)
    return JournalEntryOut.model_validate(entry)


@router.get("/journal-entries", response_model=list[JournalEntryOut], dependencies=[require("accounting.view")])
def list_journal_entries(ctx: CurrentCompany, db: DbSession) -> list[JournalEntryOut]:
    return [JournalEntryOut.model_validate(e) for e in service.list_entries(db, ctx.company.id)]


@router.get("/journal-entries/{entry_id}", response_model=JournalEntryOut, dependencies=[require("accounting.view")])
def get_journal_entry(entry_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> JournalEntryOut:
    return JournalEntryOut.model_validate(service.get_entry(db, ctx.company.id, entry_id))


@router.post("/journal-entries/{entry_id}/post", response_model=JournalEntryOut, dependencies=[require("accounting.post_entry")])
def post_journal_entry(entry_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> JournalEntryOut:
    entry = service.post_entry(db, ctx.company.id, entry_id, ctx.membership.user_id)
    return JournalEntryOut.model_validate(entry)


@router.post("/journal-entries/{entry_id}/reverse", response_model=JournalEntryOut, dependencies=[require("accounting.post_entry")])
def reverse_journal_entry(entry_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> JournalEntryOut:
    reversal = service.reverse_entry(db, ctx.company.id, entry_id, ctx.membership.user_id)
    return JournalEntryOut.model_validate(reversal)
