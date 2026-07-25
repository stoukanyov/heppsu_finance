"""API рутер за счетоводни справки (tenant-scoped)."""
import datetime as dt
import uuid

from fastapi import APIRouter

from app.api.deps import CurrentCompany, DbSession
from app.modules.reports import service
from app.modules.reports.schemas import (
    BalanceSheetOut,
    CashFlowOut,
    GeneralLedgerOut,
    KpiSummaryOut,
    ProfitAndLossOut,
    TrialBalanceOut,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/trial-balance", response_model=TrialBalanceOut)
def trial_balance(
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> TrialBalanceOut:
    """Оборотна ведомост: начални салда, обороти и крайни салда по сметки."""
    return service.trial_balance(db, ctx.company.id, date_from, date_to)


@router.get("/profit-and-loss", response_model=ProfitAndLossOut)
def profit_and_loss(
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> ProfitAndLossOut:
    """Отчет за приходите и разходите (ОПР): приходи, разходи и финансов резултат."""
    return service.profit_and_loss(db, ctx.company.id, date_from, date_to)


@router.get("/kpis", response_model=KpiSummaryOut)
def kpis(
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> KpiSummaryOut:
    """KPI обобщение за период (за дашборд и сравнение с предходен период)."""
    return service.kpi_summary(db, ctx.company.id, date_from, date_to)


@router.get("/balance-sheet", response_model=BalanceSheetOut)
def balance_sheet(
    ctx: CurrentCompany,
    db: DbSession,
    as_of: dt.date | None = None,
) -> BalanceSheetOut:
    """Счетоводен баланс към дата: активи, собствен капитал и задължения."""
    return service.balance_sheet(db, ctx.company.id, as_of)


@router.get("/cash-flow", response_model=CashFlowOut)
def cash_flow(
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> CashFlowOut:
    """Отчет за паричните потоци: оперативна, инвестиционна и финансова дейност."""
    return service.cash_flow(db, ctx.company.id, date_from, date_to)


@router.get("/general-ledger/{account_id}", response_model=GeneralLedgerOut)
def general_ledger(
    account_id: uuid.UUID,
    ctx: CurrentCompany,
    db: DbSession,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> GeneralLedgerOut:
    """Главна книга по сметка: начално салдо, хронологични движения, крайно салдо."""
    return service.general_ledger(db, ctx.company.id, account_id, date_from, date_to)
