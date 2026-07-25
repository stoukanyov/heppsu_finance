"""Изчисляване на счетоводни справки от осчетоводените операции.

Взимат се записи със статус POSTED, REVERSED и REVERSAL. Сторнираният оригинал
(REVERSED) и неговото сторно (REVERSAL) остават в книгите и взаимно се компенсират —
това е коректното счетоводно поведение. Черновите (DRAFT) не участват.

Периодизацията е по `document_date` (счетоводната дата на документа, по която се определя
и счетоводният период), а не по `posting_date` (техническата дата на осчетоводяване).

Забележка: агрегацията е в Python за яснота (подходящо за текущите обеми). При голям
обем справките ще се пренапишат към SQL агрегати.
"""
import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounting.models import (
    Account,
    AccountType,
    EntryStatus,
    JournalEntry,
    JournalLine,
)
from app.modules.companies.models import Company
from app.modules.reports.schemas import (
    BalanceLine,
    BalanceSection,
    BalanceSheetOut,
    CashFlowOut,
    CashFlowSection,
    GeneralLedgerOut,
    KpiPoint,
    KpiSeriesOut,
    KpiSummaryOut,
    LedgerLine,
    PnlGroup,
    PnlLine,
    PnlSection,
    ProfitAndLossOut,
    TrialBalanceOut,
    TrialBalanceRow,
)

# ---- Мапинг сметка → статия от официалния ОПР по НСС (Приложение № 2 към СС 1) ----
# (пореден №, наименование на статията)
_NSS_REVENUE = {
    "701": (1, "Нетни приходи от продажби на продукция"),
    "702": (1, "Нетни приходи от продажби на стоки"),
    "703": (1, "Нетни приходи от продажби на услуги"),
    "704": (1, "Нетни приходи от продажби"),
    "705": (1, "Нетни приходи от продажби"),
    "709": (2, "Други приходи от дейността"),
}
_NSS_EXPENSE = {
    "601": (1, "Разходи за материали"),
    "602": (2, "Разходи за външни услуги"),
    "603": (3, "Разходи за амортизации"),
    "604": (4, "Разходи за възнаграждения"),
    "605": (5, "Разходи за осигуровки"),
    "606": (5, "Разходи за осигуровки"),
    "609": (6, "Други разходи"),
}


def _nss_revenue_group(code: str) -> tuple[int, str]:
    if code in _NSS_REVENUE:
        return _NSS_REVENUE[code]
    if code.startswith("72"):
        return (8, "Финансови приходи")
    if code.startswith("70"):
        return (1, "Нетни приходи от продажби")
    return (9, "Други приходи")


def _nss_expense_group(code: str) -> tuple[int, str]:
    if code in _NSS_EXPENSE:
        return _NSS_EXPENSE[code]
    if code.startswith("62"):
        return (8, "Финансови разходи")
    if code.startswith("60"):
        return (6, "Други разходи")
    return (9, "Други разходи за дейността")


def _group_pnl(lines: list[PnlLine], classifier) -> list[PnlGroup]:
    buckets: dict[tuple[int, str], Decimal] = {}
    for line in lines:
        key = classifier(line.code)
        buckets[key] = buckets.get(key, ZERO) + line.amount
    ordered = sorted(buckets.items(), key=lambda kv: kv[0][0])
    return [PnlGroup(title=title, amount=amt) for (_order, title), amt in ordered if amt != ZERO]

ZERO = Decimal("0.00")
POSTED_LIKE = (EntryStatus.POSTED, EntryStatus.REVERSED, EntryStatus.REVERSAL)


def _posted_lines(db: Session, company_id: uuid.UUID):
    """Връща (JournalLine, JournalEntry) за всички осчетоводени редове на компанията."""
    stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalEntry.company_id == company_id,
            JournalEntry.status.in_(POSTED_LIKE),
        )
    )
    return db.execute(stmt).all()


def trial_balance(
    db: Session,
    company_id: uuid.UUID,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> TrialBalanceOut:
    accounts = {
        a.id: a
        for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }
    # За всяка сметка: [opening_debit, opening_credit, period_debit, period_credit]
    agg: dict[uuid.UUID, list[Decimal]] = {}

    for line, entry in _posted_lines(db, company_id):
        pdate = entry.document_date
        if date_to and pdate > date_to:
            continue
        bucket = agg.setdefault(line.account_id, [ZERO, ZERO, ZERO, ZERO])
        if date_from and pdate < date_from:
            bucket[0] += line.debit_base
            bucket[1] += line.credit_base
        else:
            bucket[2] += line.debit_base
            bucket[3] += line.credit_base

    rows: list[TrialBalanceRow] = []
    total_debit = ZERO
    total_credit = ZERO
    for account_id, (op_d, op_c, per_d, per_c) in agg.items():
        opening = op_d - op_c
        closing = opening + per_d - per_c
        if opening == ZERO and per_d == ZERO and per_c == ZERO and closing == ZERO:
            continue
        account = accounts.get(account_id)
        if account is None:
            continue
        rows.append(
            TrialBalanceRow(
                account_id=account_id,
                code=account.code,
                name=account.name,
                type=account.type,
                opening_balance=opening,
                debit_turnover=per_d,
                credit_turnover=per_c,
                closing_balance=closing,
            )
        )
        total_debit += per_d
        total_credit += per_c

    rows.sort(key=lambda r: r.code)
    return TrialBalanceOut(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total_debit_turnover=total_debit,
        total_credit_turnover=total_credit,
        is_balanced=(total_debit == total_credit),
    )


def general_ledger(
    db: Session,
    company_id: uuid.UUID,
    account_id: uuid.UUID,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> GeneralLedgerOut:
    account = db.get(Account, account_id)
    if account is None or account.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сметката не е намерена")

    movements = [
        (line, entry)
        for line, entry in _posted_lines(db, company_id)
        if line.account_id == account_id and not (date_to and entry.document_date > date_to)
    ]
    # Хронологично: по счетоводна дата на документа, после по пореден номер.
    movements.sort(key=lambda m: (m[1].document_date, m[1].entry_number or 0))

    opening = ZERO
    period: list[tuple[JournalLine, JournalEntry]] = []
    for line, entry in movements:
        if date_from and entry.document_date < date_from:
            opening += line.debit_base - line.credit_base
        else:
            period.append((line, entry))

    running = opening
    total_debit = ZERO
    total_credit = ZERO
    lines: list[LedgerLine] = []
    for line, entry in period:
        running += line.debit_base - line.credit_base
        total_debit += line.debit_base
        total_credit += line.credit_base
        lines.append(
            LedgerLine(
                entry_id=entry.id,
                entry_number=entry.entry_number,
                status=entry.status,
                posting_date=entry.posting_date,
                document_date=entry.document_date,
                document_type=entry.document_type,
                document_number=entry.document_number,
                description=line.description or entry.description,
                debit=line.debit_base,
                credit=line.credit_base,
                running_balance=running,
            )
        )

    return GeneralLedgerOut(
        account_id=account.id,
        account_code=account.code,
        account_name=account.name,
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        lines=lines,
        closing_balance=running,
        total_debit=total_debit,
        total_credit=total_credit,
    )


def profit_and_loss(
    db: Session,
    company_id: uuid.UUID,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> ProfitAndLossOut:
    """Отчет за приходите и разходите (ОПР) — потоков отчет за периода.

    Работи с оборотите (движенията) в периода, не с крайни салда: приходите
    се вземат по кредитен нетен оборот, разходите — по дебитен. Периодът се
    определя по `document_date` (счетоводната дата), както при другите справки.
    """
    accounts = {
        a.id: a
        for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }
    # За всяка сметка: [debit_period, credit_period]
    agg: dict[uuid.UUID, list[Decimal]] = {}
    for line, entry in _posted_lines(db, company_id):
        pdate = entry.document_date
        if date_from and pdate < date_from:
            continue
        if date_to and pdate > date_to:
            continue
        bucket = agg.setdefault(line.account_id, [ZERO, ZERO])
        bucket[0] += line.debit_base
        bucket[1] += line.credit_base

    revenue_lines: list[PnlLine] = []
    expense_lines: list[PnlLine] = []
    revenue_total = ZERO
    expense_total = ZERO

    for account_id, (deb, cred) in agg.items():
        account = accounts.get(account_id)
        if account is None:
            continue
        if account.type == AccountType.REVENUE:
            amount = cred - deb  # приходите са с кредитен оборот
            if amount == ZERO:
                continue
            revenue_lines.append(
                PnlLine(account_id=account_id, code=account.code, name=account.name, amount=amount)
            )
            revenue_total += amount
        elif account.type == AccountType.EXPENSE:
            amount = deb - cred  # разходите са с дебитен оборот
            if amount == ZERO:
                continue
            expense_lines.append(
                PnlLine(account_id=account_id, code=account.code, name=account.name, amount=amount)
            )
            expense_total += amount

    revenue_lines.sort(key=lambda r: r.code)
    expense_lines.sort(key=lambda r: r.code)
    net = revenue_total - expense_total

    return ProfitAndLossOut(
        date_from=date_from,
        date_to=date_to,
        revenue=PnlSection(title="Приходи", lines=revenue_lines, total=revenue_total),
        expenses=PnlSection(title="Разходи", lines=expense_lines, total=expense_total),
        revenue_groups=_group_pnl(revenue_lines, _nss_revenue_group),
        expense_groups=_group_pnl(expense_lines, _nss_expense_group),
        gross_profit=net,
        net_profit=net,
        is_profit=(net >= ZERO),
    )


def _is_cash_code(code: str) -> bool:
    return code.startswith("50")


def kpi_summary(
    db: Session,
    company_id: uuid.UUID,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> KpiSummaryOut:
    """Ключови показатели за период: потоци (приходи/разходи/печалба) за [from, to]
    и салда (пари/вземания/задължения) към date_to. Ползва се и за сравнителен период.
    """
    pnl = profit_and_loss(db, company_id, date_from, date_to)
    accounts = {
        a.id: a for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }
    cash = receivables = payables = ZERO
    for line, entry in _posted_lines(db, company_id):
        if date_to and entry.document_date > date_to:
            continue
        acc = accounts.get(line.account_id)
        if acc is None:
            continue
        delta = line.debit_base - line.credit_base
        if _is_cash_code(acc.code):
            cash += delta
        elif acc.code == "411":
            receivables += delta
        elif acc.code == "401":
            payables += -delta
    return KpiSummaryOut(
        date_from=date_from,
        date_to=date_to,
        revenue=pnl.revenue.total,
        expenses=pnl.expenses.total,
        profit=pnl.net_profit,
        cash=cash,
        receivables=receivables,
        payables=payables,
    )


_MONTHS_BG = (
    "януари", "февруари", "март", "април", "май", "юни",
    "юли", "август", "септември", "октомври", "ноември", "декември",
)


def _month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    first = dt.date(year, month, 1)
    last = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    return first, last


def kpi_series(
    db: Session,
    company_id: uuid.UUID,
    months: int = 6,
    end: dt.date | None = None,
) -> KpiSeriesOut:
    """Приходи/разходи/печалба по месеци + салдо на парите в края на всеки месец.

    Прави ЕДИН обход над осчетоводените редове (за разлика от N заявки към
    `kpi_summary`), защото се ползва при всяко зареждане на таблото.
    """
    months = max(1, min(months, 36))
    end = end or dt.date.today()
    accounts = {
        a.id: a for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }

    # Хронологичен списък от (година, месец) за прозореца, най-старият първи.
    window: list[tuple[int, int]] = []
    y, m = end.year, end.month
    for _ in range(months):
        window.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    window.reverse()
    index = {ym: i for i, ym in enumerate(window)}
    start_of_window = _month_bounds(*window[0])[0]
    end_of_window = _month_bounds(*window[-1])[1]

    revenue = [ZERO] * months
    expenses = [ZERO] * months
    # Парите са САЛДО: движенията преди прозореца дават началното салдо, след което
    # всеки месец натрупва върху предходния.
    cash_delta = [ZERO] * months
    cash_opening = ZERO

    for line, entry in _posted_lines(db, company_id):
        acc = accounts.get(line.account_id)
        if acc is None:
            continue
        pdate = entry.document_date
        if pdate > end_of_window:
            continue
        if _is_cash_code(acc.code):
            delta = line.debit_base - line.credit_base
            if pdate < start_of_window:
                cash_opening += delta
            else:
                cash_delta[index[(pdate.year, pdate.month)]] += delta
        if pdate < start_of_window:
            continue
        i = index[(pdate.year, pdate.month)]
        if acc.type == AccountType.REVENUE:
            revenue[i] += line.credit_base - line.debit_base
        elif acc.type == AccountType.EXPENSE:
            expenses[i] += line.debit_base - line.credit_base

    company = db.get(Company, company_id)
    points: list[KpiPoint] = []
    running = cash_opening
    for i, (yy, mm) in enumerate(window):
        running += cash_delta[i]
        first, last = _month_bounds(yy, mm)
        points.append(
            KpiPoint(
                period=f"{yy}-{mm:02d}",
                label=_MONTHS_BG[mm - 1],
                date_from=first,
                date_to=last,
                revenue=revenue[i],
                expenses=expenses[i],
                profit=revenue[i] - expenses[i],
                cash=running,
            )
        )
    return KpiSeriesOut(
        points=points, currency=(company.base_currency if company else "EUR")
    )


def balance_sheet(
    db: Session, company_id: uuid.UUID, as_of: dt.date | None = None
) -> BalanceSheetOut:
    """Счетоводен баланс към дата (as_of). Кумулативни салда от началото.

    Активите се вземат с дебитно салдо (амортизацията 24x е контра-актив с кредитно
    салдо и естествено намалява дълготрайните активи). Пасивите и капиталът — с
    кредитно салдо. Финансовият резултат за периода (приходи − разходи, все още
    незатворени към с/ка 122/121) се добавя към собствения капитал, за да балансира.
    """
    accounts = {
        a.id: a for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }
    bal: dict[uuid.UUID, Decimal] = {}
    revenue_total = ZERO
    expense_total = ZERO
    for line, entry in _posted_lines(db, company_id):
        if as_of and entry.document_date > as_of:
            continue
        acc = accounts.get(line.account_id)
        if acc is None:
            continue
        delta = line.debit_base - line.credit_base
        bal[line.account_id] = bal.get(line.account_id, ZERO) + delta
        if acc.type == AccountType.REVENUE:
            revenue_total += -delta
        elif acc.type == AccountType.EXPENSE:
            expense_total += delta
    current_result = revenue_total - expense_total

    noncurrent: list[BalanceLine] = []
    current: list[BalanceLine] = []
    equity: list[BalanceLine] = []
    liabilities: list[BalanceLine] = []

    for account_id, closing in bal.items():
        acc = accounts[account_id]
        if acc.type == AccountType.ASSET:
            amount = closing
            if amount == ZERO:
                continue
            line = BalanceLine(account_id=account_id, code=acc.code, name=acc.name, amount=amount)
            (noncurrent if acc.code.startswith("2") else current).append(line)
        elif acc.type == AccountType.LIABILITY:
            amount = -closing
            if amount == ZERO:
                continue
            liabilities.append(BalanceLine(account_id=account_id, code=acc.code, name=acc.name, amount=amount))
        elif acc.type == AccountType.EQUITY:
            amount = -closing
            if amount == ZERO:
                continue
            equity.append(BalanceLine(account_id=account_id, code=acc.code, name=acc.name, amount=amount))

    if current_result != ZERO:
        equity.append(
            BalanceLine(code="122", name="Финансов резултат за периода", amount=current_result)
        )

    for lst in (noncurrent, current, equity, liabilities):
        lst.sort(key=lambda x: x.code)

    nc_total = sum((l.amount for l in noncurrent), ZERO)
    c_total = sum((l.amount for l in current), ZERO)
    eq_total = sum((l.amount for l in equity), ZERO)
    li_total = sum((l.amount for l in liabilities), ZERO)
    assets_total = nc_total + c_total
    passives_total = eq_total + li_total

    return BalanceSheetOut(
        as_of=as_of,
        assets=[
            BalanceSection(title="Нетекущи (дълготрайни) активи", lines=noncurrent, total=nc_total),
            BalanceSection(title="Текущи активи", lines=current, total=c_total),
        ],
        assets_total=assets_total,
        passives=[
            BalanceSection(title="Собствен капитал", lines=equity, total=eq_total),
            BalanceSection(title="Задължения", lines=liabilities, total=li_total),
        ],
        passives_total=passives_total,
        is_balanced=(assets_total == passives_total),
    )


def cash_flow(
    db: Session,
    company_id: uuid.UUID,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> CashFlowOut:
    """Отчет за паричните потоци (пряк метод по кореспондиращи сметки).

    За всяка осчетоводена операция, засягаща парична сметка (50x), паричното движение
    се класифицира по типа на кореспондиращите сметки: оперативна (приходи/разходи,
    клиенти/доставчици, персонал, данъци), инвестиционна (дълготрайни активи, код 2x)
    или финансова (собствен капитал / заеми).
    """
    accounts = {
        a.id: a for a in db.scalars(select(Account).where(Account.company_id == company_id))
    }
    # групиране на редовете по операция
    entries: dict[uuid.UUID, list] = {}
    entry_date: dict[uuid.UUID, dt.date] = {}
    for line, entry in _posted_lines(db, company_id):
        entries.setdefault(entry.id, []).append(line)
        entry_date[entry.id] = entry.document_date

    opening = ZERO
    op_net = inv_net = fin_net = ZERO
    op_in = op_out = inv_in = inv_out = fin_in = fin_out = ZERO

    def classify(other_lines) -> str:
        for l in other_lines:
            acc = accounts.get(l.account_id)
            if acc is None:
                continue
            if acc.code.startswith("2"):
                return "INVEST"
            if acc.type == AccountType.EQUITY or acc.code.startswith("15"):
                return "FINANCE"
        return "OPERATING"

    for eid, lines in entries.items():
        edate = entry_date[eid]
        cash_delta = ZERO
        for l in lines:
            acc = accounts.get(l.account_id)
            if acc is not None and _is_cash_code(acc.code):
                cash_delta += l.debit_base - l.credit_base
        if cash_delta == ZERO:
            continue
        # преди периода → трупа се в началното салдо
        if date_from and edate < date_from:
            opening += cash_delta
            continue
        if date_to and edate > date_to:
            continue
        other = [l for l in lines if not (accounts.get(l.account_id) and _is_cash_code(accounts[l.account_id].code))]
        cat = classify(other)
        if cat == "INVEST":
            inv_net += cash_delta
            if cash_delta > 0:
                inv_in += cash_delta
            else:
                inv_out += cash_delta
        elif cat == "FINANCE":
            fin_net += cash_delta
            if cash_delta > 0:
                fin_in += cash_delta
            else:
                fin_out += cash_delta
        else:
            op_net += cash_delta
            if cash_delta > 0:
                op_in += cash_delta
            else:
                op_out += cash_delta

    net_change = op_net + inv_net + fin_net
    closing = opening + net_change
    return CashFlowOut(
        date_from=date_from,
        date_to=date_to,
        opening_cash=opening,
        sections=[
            CashFlowSection(title="Оперативна дейност", inflow=op_in, outflow=-op_out, net=op_net),
            CashFlowSection(title="Инвестиционна дейност", inflow=inv_in, outflow=-inv_out, net=inv_net),
            CashFlowSection(title="Финансова дейност", inflow=fin_in, outflow=-fin_out, net=fin_net),
        ],
        net_change=net_change,
        closing_cash=closing,
        reconciles=(opening + net_change == closing),
    )
