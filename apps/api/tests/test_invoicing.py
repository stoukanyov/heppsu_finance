from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"
CP = "/api/v1/counterparties"
INV = "/api/v1/invoices"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c for c in client.post(f"{VAT}/codes/seed", headers=h).json()}
    cust = client.post(f"{CP}", headers=h, json={"type": "CUSTOMER", "name": "Клиент ООД", "vat_number": "BG111222333"}).json()["id"]
    return h, codes, cust


def _payload(cust, code_id, qty="2", price="500.00", itype="INVOICE"):
    return {
        "counterparty_id": cust,
        "invoice_type": itype,
        "issue_date": "2026-07-15",
        "vat_code_id": code_id,
        "lines": [{"description": "Консултантска услуга", "quantity": qty, "unit_price": price}],
    }


def _period_id(client, h, code="2026-07"):
    year = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    return next(p["id"] for p in year["periods"] if p["code"] == code)


def test_create_and_issue(client):
    h, codes, cust = _setup(client, "inv1@example.com")
    r = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"]))
    assert r.status_code == 201, r.text
    inv = r.json()
    assert float(inv["subtotal"]) == 1000.0
    assert float(inv["vat_amount"]) == 200.0
    assert float(inv["total"]) == 1200.0
    assert inv["status"] == "DRAFT" and inv["number"] is None

    r = client.post(f"{INV}/{inv['id']}/issue", headers=h)
    assert r.status_code == 200, r.text
    issued = r.json()
    assert issued["status"] == "ISSUED"
    assert issued["number"] == 1
    assert issued["full_number"] == "0000000001"
    assert issued["journal_entry_id"] and issued["vat_entry_id"]

    # осчетоводяване: 411 Дт 1200, 703 Кт 1000, 4532 Кт 200
    tb = {r["code"]: r for r in client.get("/api/v1/reports/trial-balance", headers=h).json()["rows"]}
    assert float(tb["411"]["debit_turnover"]) == 1200.0
    assert float(tb["703"]["credit_turnover"]) == 1000.0
    assert float(tb["4532"]["credit_turnover"]) == 200.0

    # ДДС дневник продажби
    ret = client.get(f"{VAT}/returns/{_period_id(client, h)}", headers=h).json()
    assert float(ret["sales"]["total_base"]) == 1000.0
    assert float(ret["sales"]["total_vat"]) == 200.0


def test_issue_twice_rejected(client):
    h, codes, cust = _setup(client, "inv2@example.com")
    iid = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()["id"]
    assert client.post(f"{INV}/{iid}/issue", headers=h).status_code == 200
    assert client.post(f"{INV}/{iid}/issue", headers=h).status_code == 409


def test_numbering_increments(client):
    h, codes, cust = _setup(client, "inv3@example.com")
    for expected in (1, 2):
        iid = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()["id"]
        num = client.post(f"{INV}/{iid}/issue", headers=h).json()["number"]
        assert num == expected


def test_cancel_draft_only(client):
    h, codes, cust = _setup(client, "inv4@example.com")
    iid = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()["id"]
    assert client.post(f"{INV}/{iid}/cancel", headers=h).json()["status"] == "CANCELLED"
    # издадена не се анулира
    iid2 = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()["id"]
    client.post(f"{INV}/{iid2}/issue", headers=h)
    assert client.post(f"{INV}/{iid2}/cancel", headers=h).status_code == 409


def test_non_customer_rejected(client):
    h, codes, _ = _setup(client, "inv5@example.com")
    supplier = client.post(CP, headers=h, json={"type": "SUPPLIER", "name": "Доставчик"}).json()["id"]
    r = client.post(INV, headers=h, json=_payload(supplier, codes["S20"]["id"]))
    assert r.status_code == 422 and "клиент" in r.json()["detail"]


def test_credit_note_reverses(client):
    h, codes, cust = _setup(client, "invcn@example.com")
    inv = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()
    client.post(f"{INV}/{inv['id']}/issue", headers=h)

    cn_payload = {**_payload(cust, codes["S20"]["id"], itype="CREDIT_NOTE"), "original_invoice_id": inv["id"]}
    cn = client.post(INV, headers=h, json=cn_payload).json()
    r = client.post(f"{INV}/{cn['id']}/issue", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["original_invoice_id"] == inv["id"]

    # фактура + огледално кредитно известие → нетен ефект нула
    tb = {x["code"]: x for x in client.get("/api/v1/reports/trial-balance", headers=h).json()["rows"]}
    assert float(tb["411"]["closing_balance"]) == 0.0
    assert float(tb["703"]["closing_balance"]) == 0.0
    assert float(tb["4532"]["closing_balance"]) == 0.0

    ret = client.get(f"{VAT}/returns/{_period_id(client, h)}", headers=h).json()
    assert float(ret["sales"]["total_base"]) == 0.0
    assert float(ret["sales"]["total_vat"]) == 0.0


def test_invoice_pdf(client):
    h, codes, cust = _setup(client, "invpdf@example.com")
    inv = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"])).json()
    client.post(f"{INV}/{inv['id']}/issue", headers=h)
    r = client.get(f"{INV}/{inv['id']}/pdf", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 500


def test_proforma_no_accounting(client):
    h, codes, cust = _setup(client, "inv6@example.com")
    iid = client.post(INV, headers=h, json=_payload(cust, codes["S20"]["id"], itype="PROFORMA")).json()["id"]
    issued = client.post(f"{INV}/{iid}/issue", headers=h).json()
    assert issued["status"] == "ISSUED" and issued["number"] == 1
    assert issued["journal_entry_id"] is None and issued["vat_entry_id"] is None
