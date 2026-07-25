from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
REP = "/api/v1/reports"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    accounts = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, accounts


def _post(client, h, acc, dr, cr, amount, date="2026-07-15"):
    payload = {
        "document_date": date,
        "document_number": "DOC",
        "lines": [
            {"account_id": acc[dr]["id"], "debit": amount, "credit": "0"},
            {"account_id": acc[cr]["id"], "debit": "0", "credit": amount},
        ],
    }
    eid = client.post(f"{ACC}/journal-entries", headers=h, json=payload).json()["id"]
    r = client.post(f"{ACC}/journal-entries/{eid}/post", headers=h)
    assert r.status_code == 200, r.text
    return eid


def _rows_by_code(tb):
    return {r["code"]: r for r in tb["rows"]}


def test_trial_balance_basic_and_balanced(client):
    h, acc = _setup(client, "tb@example.com")
    _post(client, h, acc, "602", "401", "100.00")   # разход / доставчик
    _post(client, h, acc, "501", "701", "500.00")   # каса / приход

    tb = client.get(f"{REP}/trial-balance", headers=h).json()
    rows = _rows_by_code(tb)
    assert float(rows["602"]["debit_turnover"]) == 100.0
    assert float(rows["602"]["closing_balance"]) == 100.0
    assert float(rows["401"]["credit_turnover"]) == 100.0
    assert float(rows["401"]["closing_balance"]) == -100.0
    assert float(rows["701"]["closing_balance"]) == -500.0

    assert float(tb["total_debit_turnover"]) == 600.0
    assert float(tb["total_credit_turnover"]) == 600.0
    assert tb["is_balanced"] is True


def test_draft_not_in_reports(client):
    h, acc = _setup(client, "draft@example.com")
    # чернова (без post) не бива да влиза в справката
    payload = {
        "document_date": "2026-07-15",
        "lines": [
            {"account_id": acc["602"]["id"], "debit": "50.00", "credit": "0"},
            {"account_id": acc["401"]["id"], "debit": "0", "credit": "50.00"},
        ],
    }
    client.post(f"{ACC}/journal-entries", headers=h, json=payload)
    tb = client.get(f"{REP}/trial-balance", headers=h).json()
    assert tb["rows"] == []


def test_general_ledger(client):
    h, acc = _setup(client, "gl@example.com")
    _post(client, h, acc, "501", "701", "500.00")
    _post(client, h, acc, "602", "501", "120.00")  # плащане в брой

    gl = client.get(f"{REP}/general-ledger/{acc['501']['id']}", headers=h).json()
    assert gl["account_code"] == "501"
    assert float(gl["opening_balance"]) == 0.0
    assert len(gl["lines"]) == 2
    # 500 дебит, после 120 кредит → крайно салдо 380
    assert float(gl["lines"][0]["running_balance"]) == 500.0
    assert float(gl["lines"][1]["running_balance"]) == 380.0
    assert float(gl["closing_balance"]) == 380.0


def test_reversal_nets_to_zero(client):
    h, acc = _setup(client, "revrep@example.com")
    eid = _post(client, h, acc, "602", "401", "100.00")
    r = client.post(f"{ACC}/journal-entries/{eid}/reverse", headers=h)
    assert r.status_code == 200

    tb = client.get(f"{REP}/trial-balance", headers=h).json()
    rows = _rows_by_code(tb)
    # оборотите остават (100 дебит + 100 кредит), но крайното салдо е 0
    assert float(rows["602"]["debit_turnover"]) == 100.0
    assert float(rows["602"]["credit_turnover"]) == 100.0
    assert float(rows["602"]["closing_balance"]) == 0.0


def test_general_ledger_unknown_account_404(client):
    h, acc = _setup(client, "gl404@example.com")
    r = client.get(f"{REP}/general-ledger/00000000-0000-0000-0000-000000000000", headers=h)
    assert r.status_code == 404


def test_trial_balance_date_filter(client):
    h, acc = _setup(client, "tbdate@example.com")
    _post(client, h, acc, "602", "401", "100.00", date="2026-06-15")
    _post(client, h, acc, "602", "401", "40.00", date="2026-07-15")

    # само юли: оборот 40, но начално салдо 100 (от юни)
    tb = client.get(f"{REP}/trial-balance?date_from=2026-07-01&date_to=2026-07-31", headers=h).json()
    row = _rows_by_code(tb)["602"]
    assert float(row["opening_balance"]) == 100.0
    assert float(row["debit_turnover"]) == 40.0
    assert float(row["closing_balance"]) == 140.0


def test_profit_and_loss(client):
    h, acc = _setup(client, "pnl@example.com")
    _post(client, h, acc, "501", "701", "5000.00")   # каса / приходи от продажби 5000
    _post(client, h, acc, "602", "401", "1800.00")   # разходи за услуги / доставчик 1800
    _post(client, h, acc, "601", "401", "700.00")    # разходи за материали / доставчик 700

    pnl = client.get(f"{REP}/profit-and-loss", headers=h).json()
    rev = {r["code"]: float(r["amount"]) for r in pnl["revenue"]["lines"]}
    exp = {r["code"]: float(r["amount"]) for r in pnl["expenses"]["lines"]}
    assert rev["701"] == 5000.0
    assert exp["602"] == 1800.0 and exp["601"] == 700.0
    assert float(pnl["revenue"]["total"]) == 5000.0
    assert float(pnl["expenses"]["total"]) == 2500.0
    assert float(pnl["net_profit"]) == 2500.0
    assert pnl["is_profit"] is True


def test_profit_and_loss_loss(client):
    h, acc = _setup(client, "pnlloss@example.com")
    _post(client, h, acc, "501", "701", "1000.00")
    _post(client, h, acc, "602", "401", "1500.00")
    pnl = client.get(f"{REP}/profit-and-loss", headers=h).json()
    assert float(pnl["net_profit"]) == -500.0
    assert pnl["is_profit"] is False


def test_profit_and_loss_date_filter(client):
    h, acc = _setup(client, "pnldate@example.com")
    _post(client, h, acc, "501", "701", "1000.00", date="2026-07-15")
    _post(client, h, acc, "501", "701", "400.00", date="2026-08-15")
    pnl = client.get(f"{REP}/profit-and-loss?date_from=2026-07-01&date_to=2026-07-31", headers=h).json()
    assert float(pnl["revenue"]["total"]) == 1000.0


def test_balance_sheet_balances(client):
    h, acc = _setup(client, "bs@example.com")
    # внасяне на капитал: банка / основен капитал
    _post(client, h, acc, "503", "101", "10000.00")
    # покупка на оборудване от банка (инвестиция)
    _post(client, h, acc, "204", "503", "4000.00")
    # приход в брой
    _post(client, h, acc, "501", "703", "6000.00")
    # разход от банка
    _post(client, h, acc, "602", "503", "1500.00")

    bs = client.get(f"{REP}/balance-sheet", headers=h).json()
    assert bs["is_balanced"] is True
    assert float(bs["assets_total"]) == float(bs["passives_total"])
    # нетекущи активи включват оборудването 204
    nc = bs["assets"][0]
    assert any(l["code"] == "204" and float(l["amount"]) == 4000.0 for l in nc["lines"])
    # финансовият резултат за периода е в собствения капитал
    eq = bs["passives"][0]
    assert any(l["code"] == "122" for l in eq["lines"])


def test_cash_flow_reconciles(client):
    h, acc = _setup(client, "cf@example.com")
    _post(client, h, acc, "503", "101", "10000.00")   # финансова: капитал
    _post(client, h, acc, "204", "503", "4000.00")    # инвестиционна: оборудване
    _post(client, h, acc, "501", "703", "6000.00")    # оперативна: приход
    _post(client, h, acc, "602", "503", "1500.00")    # оперативна: разход

    cf = client.get(f"{REP}/cash-flow", headers=h).json()
    secs = {s["title"]: s for s in cf["sections"]}
    assert float(secs["Финансова дейност"]["net"]) == 10000.0
    assert float(secs["Инвестиционна дейност"]["net"]) == -4000.0
    assert float(secs["Оперативна дейност"]["net"]) == 4500.0   # +6000 -1500
    assert float(cf["net_change"]) == 10500.0
    assert float(cf["closing_cash"]) == 10500.0
    assert cf["reconciles"] is True


def test_cash_flow_opening_balance(client):
    h, acc = _setup(client, "cfopen@example.com")
    _post(client, h, acc, "501", "703", "1000.00", date="2026-06-15")   # преди периода
    _post(client, h, acc, "501", "703", "500.00", date="2026-07-15")    # в периода
    cf = client.get(f"{REP}/cash-flow?date_from=2026-07-01&date_to=2026-07-31", headers=h).json()
    assert float(cf["opening_cash"]) == 1000.0
    assert float(cf["net_change"]) == 500.0
    assert float(cf["closing_cash"]) == 1500.0


def test_pnl_nss_grouping(client):
    h, acc = _setup(client, "pnlnss@example.com")
    _post(client, h, acc, "501", "703", "10000.00")   # приходи от услуги
    _post(client, h, acc, "501", "709", "500.00")      # други приходи
    _post(client, h, acc, "602", "401", "2000.00")     # външни услуги
    _post(client, h, acc, "604", "421", "3000.00")     # възнаграждения
    _post(client, h, acc, "605", "461", "700.00")      # осигуровки
    pnl = client.get(f"{REP}/profit-and-loss", headers=h).json()
    rg = {g["title"]: float(g["amount"]) for g in pnl["revenue_groups"]}
    eg = {g["title"]: float(g["amount"]) for g in pnl["expense_groups"]}
    assert rg["Нетни приходи от продажби на услуги"] == 10000.0
    assert rg["Други приходи от дейността"] == 500.0
    assert eg["Разходи за външни услуги"] == 2000.0
    assert eg["Разходи за възнаграждения"] == 3000.0
    assert eg["Разходи за осигуровки"] == 700.0
