"""Pydantic схеми за счетоводните справки (в базова валута)."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.modules.accounting.models import AccountType, EntryStatus


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    type: AccountType
    opening_balance: Decimal   # начално салдо (дебит − кредит)
    debit_turnover: Decimal    # дебитен оборот за периода
    credit_turnover: Decimal   # кредитен оборот за периода
    closing_balance: Decimal   # крайно салдо (дебит − кредит)


class TrialBalanceOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    rows: list[TrialBalanceRow]
    total_debit_turnover: Decimal
    total_credit_turnover: Decimal
    is_balanced: bool


class LedgerLine(BaseModel):
    entry_id: uuid.UUID
    entry_number: int | None
    status: EntryStatus
    posting_date: dt.date | None
    document_date: dt.date
    document_type: str | None
    document_number: str | None
    description: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class GeneralLedgerOut(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    date_from: dt.date | None
    date_to: dt.date | None
    opening_balance: Decimal
    lines: list[LedgerLine]
    closing_balance: Decimal
    total_debit: Decimal
    total_credit: Decimal


# ---------- Отчет за приходите и разходите (ОПР / P&L) ----------
class PnlLine(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    amount: Decimal  # положителна стойност за периода (приход или разход)


class PnlSection(BaseModel):
    title: str            # напр. "Приходи" / "Разходи"
    lines: list[PnlLine]
    total: Decimal


class PnlGroup(BaseModel):
    """Статия от официалния ОПР по НСС (напр. „Разходи за материали")."""

    title: str
    amount: Decimal


class ProfitAndLossOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    revenue: PnlSection
    expenses: PnlSection
    # Групиране по официалните статии на ОПР по НСС (за законовия формат):
    revenue_groups: list[PnlGroup] = []
    expense_groups: list[PnlGroup] = []
    gross_profit: Decimal      # приходи − разходи преди данъци (тук = нетна печалба)
    net_profit: Decimal        # печалба/загуба за периода
    is_profit: bool


# ---------- Счетоводен баланс ----------
class BalanceLine(BaseModel):
    account_id: uuid.UUID | None = None
    code: str
    name: str
    amount: Decimal


class BalanceSection(BaseModel):
    title: str
    lines: list[BalanceLine]
    total: Decimal


class BalanceSheetOut(BaseModel):
    as_of: dt.date | None
    assets: list[BalanceSection]              # Нетекущи / Текущи активи
    assets_total: Decimal
    passives: list[BalanceSection]            # Собствен капитал / Задължения
    passives_total: Decimal
    is_balanced: bool


# ---------- Отчет за паричните потоци ----------
class CashFlowSection(BaseModel):
    title: str        # Оперативна / Инвестиционна / Финансова дейност
    inflow: Decimal
    outflow: Decimal
    net: Decimal


class CashFlowOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    opening_cash: Decimal
    sections: list[CashFlowSection]
    net_change: Decimal
    closing_cash: Decimal
    reconciles: bool   # opening + net_change == closing


# ---------- KPI обобщение (за дашборд + сравнителен период) ----------
class KpiSummaryOut(BaseModel):
    date_from: dt.date | None
    date_to: dt.date | None
    revenue: Decimal       # приход за периода (поток)
    expenses: Decimal      # разход за периода (поток)
    profit: Decimal        # финансов резултат за периода
    cash: Decimal          # налични парични средства към date_to (салдо)
    receivables: Decimal   # вземания от клиенти към date_to
    payables: Decimal      # задължения към доставчици към date_to
