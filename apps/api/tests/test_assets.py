from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
FA = "/api/v1/fixed-assets"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _asset_payload(acc, invno="A-001", accounts=True):
    p = {
        "inventory_number": invno,
        "name": "Лаптоп",
        "category": "Оборудване",
        "acquisition_date": "2026-01-10",
        "in_service_date": "2026-01-15",
        "initial_cost": "1200.00",
        "residual_value": "0.00",
        "useful_life_months": 12,
    }
    if accounts:
        p["gl_expense_account_id"] = acc["603"]["id"]
        p["gl_accum_account_id"] = acc["241"]["id"]
    return p


def test_create_and_schedule(client):
    h, acc = _setup(client, "asset1@example.com")
    r = client.post(FA, headers=h, json=_asset_payload(acc))
    assert r.status_code == 201, r.text
    asset = r.json()
    assert float(asset["net_book_value"]) == 1200.0
    aid = asset["id"]

    sched = client.get(f"{FA}/{aid}/schedule", headers=h).json()
    assert len(sched) == 12
    assert sched[0]["year"] == 2026 and sched[0]["month"] == 1
    assert float(sched[0]["amount"]) == 100.0
    assert float(sched[-1]["cumulative"]) == 1200.0


def test_duplicate_inventory_number(client):
    h, acc = _setup(client, "asset2@example.com")
    client.post(FA, headers=h, json=_asset_payload(acc, invno="DUP"))
    r = client.post(FA, headers=h, json=_asset_payload(acc, invno="DUP"))
    assert r.status_code == 409


def test_depreciation_run(client):
    h, acc = _setup(client, "asset3@example.com")
    client.post(FA, headers=h, json=_asset_payload(acc))
    r = client.post(f"{FA}/depreciation-run", headers=h, json={"year": 2026, "month": 7})
    assert r.status_code == 200
    props = r.json()
    assert len(props) == 1 and float(props[0]["amount"]) == 100.0


def test_depreciate_posts_entry(client):
    h, acc = _setup(client, "asset4@example.com")
    aid = client.post(FA, headers=h, json=_asset_payload(acc)).json()["id"]

    r = client.post(f"{FA}/{aid}/depreciate", headers=h, json={"year": 2026, "month": 7})
    assert r.status_code == 201, r.text
    depr = r.json()
    assert float(depr["amount"]) == 100.0
    assert depr["journal_entry_id"] is not None

    asset = client.get(f"{FA}/{aid}", headers=h).json()
    assert float(asset["accumulated_depreciation"]) == 100.0
    assert float(asset["net_book_value"]) == 1100.0

    # отразено в оборотната ведомост: разход за амортизация 603
    tb = client.get("/api/v1/reports/trial-balance", headers=h).json()
    row = next(r for r in tb["rows"] if r["code"] == "603")
    assert float(row["debit_turnover"]) == 100.0

    # повторно за същия месец → 409
    r = client.post(f"{FA}/{aid}/depreciate", headers=h, json={"year": 2026, "month": 7})
    assert r.status_code == 409


def test_depreciate_requires_accounts(client):
    h, acc = _setup(client, "asset5@example.com")
    aid = client.post(FA, headers=h, json=_asset_payload(acc, invno="NOACC", accounts=False)).json()["id"]
    r = client.post(f"{FA}/{aid}/depreciate", headers=h, json={"year": 2026, "month": 7})
    assert r.status_code == 422
    assert "сметки" in r.json()["detail"].lower()


def test_tenant_isolation(client):
    h_a, acc = _setup(client, "asset-a@example.com")
    aid = client.post(FA, headers=h_a, json=_asset_payload(acc)).json()["id"]
    h_b, _ = _setup(client, "asset-b@example.com")
    assert client.get(f"{FA}/{aid}", headers=h_b).status_code == 404
