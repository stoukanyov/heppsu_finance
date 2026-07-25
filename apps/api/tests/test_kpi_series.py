"""Тестове за времевия ряд по месеци, който захранва графиките на таблото."""
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
REP = "/api/v1/reports"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth,
                      json={"name": "Тест ЕООД", "eik": "208418861"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _post(client, h, acc, dr, cr, amount, date, num="OP"):
    e = client.post(f"{ACC}/journal-entries", headers=h, json={
        "document_date": date, "document_number": num,
        "lines": [{"account_id": acc[dr]["id"], "debit": amount, "credit": "0"},
                  {"account_id": acc[cr]["id"], "debit": "0", "credit": amount}],
    }).json()
    client.post(f"{ACC}/journal-entries/{e['id']}/post", headers=h)


def _series(client, h, months=6, end="2026-07-31"):
    return client.get(f"{REP}/kpi-series?months={months}&end={end}", headers=h).json()


def test_series_returns_one_point_per_month_chronologically(client):
    h, _ = _setup(client, "series-shape@example.com")
    data = _series(client, h, months=6)
    assert data["currency"] == "EUR"
    assert [p["period"] for p in data["points"]] == [
        "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    assert data["points"][0]["label"] == "февруари"
    assert data["points"][0]["date_from"] == "2026-02-01"
    assert data["points"][0]["date_to"] == "2026-02-28"
    assert data["points"][-1]["date_to"] == "2026-07-31"


def test_revenue_and_expenses_land_in_their_own_month(client):
    h, acc = _setup(client, "series-buckets@example.com")
    _post(client, h, acc, "501", "703", "1000.00", "2026-05-10", "MAY-REV")
    _post(client, h, acc, "602", "501", "300.00", "2026-06-12", "JUN-EXP")

    pts = {p["period"]: p for p in _series(client, h)["points"]}
    assert pts["2026-05"]["revenue"] == "1000.00"
    assert pts["2026-05"]["expenses"] == "0.00"
    assert pts["2026-05"]["profit"] == "1000.00"
    assert pts["2026-06"]["expenses"] == "300.00"
    assert pts["2026-06"]["profit"] == "-300.00"
    assert pts["2026-07"]["revenue"] == "0.00"


def test_cash_is_a_running_balance_not_a_monthly_flow(client):
    """Парите са салдо: всеки месец носи натрупаното от предходните."""
    h, acc = _setup(client, "series-cash@example.com")
    _post(client, h, acc, "501", "703", "1000.00", "2026-05-10", "IN-1")
    _post(client, h, acc, "602", "501", "400.00", "2026-06-12", "OUT-1")

    pts = {p["period"]: p for p in _series(client, h)["points"]}
    assert pts["2026-04"]["cash"] == "0.00"
    assert pts["2026-05"]["cash"] == "1000.00"
    assert pts["2026-06"]["cash"] == "600.00"
    assert pts["2026-07"]["cash"] == "600.00"       # без движения — салдото се запазва


def test_movements_before_the_window_form_the_opening_cash(client):
    h, acc = _setup(client, "series-opening@example.com")
    _post(client, h, acc, "501", "703", "5000.00", "2026-01-15", "OLD")

    pts = {p["period"]: p for p in _series(client, h, months=3)["points"]}
    assert set(pts) == {"2026-05", "2026-06", "2026-07"}
    # приходът е извън прозореца → не влиза в потоците, но остава в салдото
    assert pts["2026-05"]["revenue"] == "0.00"
    assert pts["2026-05"]["cash"] == "5000.00"


def test_future_and_draft_entries_are_excluded(client):
    h, acc = _setup(client, "series-excluded@example.com")
    _post(client, h, acc, "501", "703", "900.00", "2026-09-01", "FUTURE")
    client.post(f"{ACC}/journal-entries", headers=h, json={          # чернова
        "document_date": "2026-07-05", "document_number": "DRAFT",
        "lines": [{"account_id": acc["501"]["id"], "debit": "77.00", "credit": "0"},
                  {"account_id": acc["703"]["id"], "debit": "0", "credit": "77.00"}],
    })
    pts = {p["period"]: p for p in _series(client, h)["points"]}
    assert pts["2026-07"]["revenue"] == "0.00"
    assert pts["2026-07"]["cash"] == "0.00"


def test_months_parameter_is_capped(client):
    h, _ = _setup(client, "series-cap@example.com")
    assert len(_series(client, h, months=999)["points"]) == 36


def test_series_requires_reports_permission(client):
    from tests.conftest import register_and_login as reg

    h, _ = _setup(client, "series-perm-owner@example.com")
    roles = {r["code"]: r for r in client.post("/api/v1/rbac/roles/seed", headers=h).json()}
    reg(client, "series-perm-emp@example.com")
    m = client.post("/api/v1/members", headers=h,
                    json={"email": "series-perm-emp@example.com", "role": "ACCOUNTANT"}).json()
    client.post(f"/api/v1/rbac/members/{m['id']}/role", headers=h,
                json={"role_id": roles["EMPLOYEE"]["id"]})
    token = client.post("/api/v1/auth/login", json={
        "email": "series-perm-emp@example.com", "password": "supersecret1"}).json()["access_token"]
    emp = {"Authorization": f"Bearer {token}", "X-Company-Id": h["X-Company-Id"]}

    r = client.get(f"{REP}/kpi-series", headers=emp)
    assert r.status_code == 403
    assert r.json()["code"] == "PERMISSION_DENIED"
