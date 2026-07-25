from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"
CP = "/api/v1/counterparties"
PUR = "/api/v1/purchase-invoices"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c for c in client.post(f"{VAT}/codes/seed", headers=h).json()}
    supplier = client.post(CP, headers=h, json={"type": "SUPPLIER", "name": "Доставчик ЕООД", "vat_number": "BG9"}).json()["id"]
    return h, acc, codes, supplier


def _payload(supplier, code_id, price="500.00", expense=None, num="SF-1"):
    p = {
        "counterparty_id": supplier,
        "supplier_document_number": num,
        "document_date": "2026-07-15",
        "vat_code_id": code_id,
        "lines": [{"description": "Услуга", "quantity": "1", "unit_price": price}],
    }
    if expense:
        p["expense_account_id"] = expense
    return p


def _period_id(client, h, code="2026-07"):
    year = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    return next(p["id"] for p in year["periods"] if p["code"] == code)


def _tb(client, h):
    return {r["code"]: r for r in client.get("/api/v1/reports/trial-balance", headers=h).json()["rows"]}


def test_create_and_post_with_credit(client):
    h, acc, codes, supplier = _setup(client, "pur1@example.com")
    r = client.post(PUR, headers=h, json=_payload(supplier, codes["P20"]["id"]))
    assert r.status_code == 201, r.text
    inv = r.json()
    assert float(inv["subtotal"]) == 500.0 and float(inv["vat_amount"]) == 100.0 and float(inv["total"]) == 600.0

    posted = client.post(f"{PUR}/{inv['id']}/post", headers=h).json()
    assert posted["status"] == "POSTED" and posted["journal_entry_id"] and posted["vat_entry_id"]

    tb = _tb(client, h)
    assert float(tb["602"]["debit_turnover"]) == 500.0
    assert float(tb["4531"]["debit_turnover"]) == 100.0
    assert float(tb["401"]["credit_turnover"]) == 600.0

    ret = client.get(f"{VAT}/returns/{_period_id(client, h)}", headers=h).json()
    assert float(ret["purchases"]["total_base"]) == 500.0
    assert float(ret["purchases"]["total_credit"]) == 100.0


def test_no_credit_vat_goes_to_expense(client):
    h, acc, codes, supplier = _setup(client, "pur2@example.com")
    inv = client.post(PUR, headers=h, json=_payload(supplier, codes["PNOCR"]["id"])).json()
    client.post(f"{PUR}/{inv['id']}/post", headers=h)
    tb = _tb(client, h)
    assert float(tb["602"]["debit_turnover"]) == 600.0  # ДДС е в разхода
    assert "4531" not in tb  # няма данъчен кредит
    ret = client.get(f"{VAT}/returns/{_period_id(client, h)}", headers=h).json()
    assert float(ret["purchases"]["total_credit"]) == 0.0


def test_custom_expense_account(client):
    h, acc, codes, supplier = _setup(client, "pur3@example.com")
    inv = client.post(PUR, headers=h, json=_payload(supplier, codes["P20"]["id"], expense=acc["601"]["id"])).json()
    client.post(f"{PUR}/{inv['id']}/post", headers=h)
    tb = _tb(client, h)
    assert float(tb["601"]["debit_turnover"]) == 500.0


def test_post_twice_and_cancel(client):
    h, acc, codes, supplier = _setup(client, "pur4@example.com")
    inv = client.post(PUR, headers=h, json=_payload(supplier, codes["P20"]["id"])).json()
    assert client.post(f"{PUR}/{inv['id']}/post", headers=h).status_code == 200
    assert client.post(f"{PUR}/{inv['id']}/post", headers=h).status_code == 409
    assert client.post(f"{PUR}/{inv['id']}/cancel", headers=h).status_code == 409  # осчетоводена

    inv2 = client.post(PUR, headers=h, json=_payload(supplier, codes["P20"]["id"], num="SF-2")).json()
    assert client.post(f"{PUR}/{inv2['id']}/cancel", headers=h).json()["status"] == "CANCELLED"


def test_non_supplier_rejected(client):
    h, acc, codes, _ = _setup(client, "pur5@example.com")
    customer = client.post(CP, headers=h, json={"type": "CUSTOMER", "name": "Клиент"}).json()["id"]
    r = client.post(PUR, headers=h, json=_payload(customer, codes["P20"]["id"]))
    assert r.status_code == 422 and "доставчик" in r.json()["detail"]
