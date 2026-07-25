from tests.conftest import register_and_login

API = "/api/v1/accounting"


def _setup(client, email: str):
    """Регистрира потребител, компания, зарежда сметкоплан и фискална 2026 г."""
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"})
    company_id = r.json()["id"]
    h = {**auth, "X-Company-Id": company_id}

    r = client.post(f"{API}/chart/seed", headers=h)
    assert r.status_code == 201, r.text
    accounts = {a["code"]: a for a in r.json()}

    r = client.post(f"{API}/fiscal-years", headers=h, json={"year": 2026})
    assert r.status_code == 201, r.text
    return h, accounts


def _entry_payload(acc, debit_account="602", credit_account="401", amount="100.00"):
    return {
        "document_date": "2026-07-15",
        "document_type": "Фактура",
        "document_number": "1000",
        "lines": [
            {"account_id": acc[debit_account]["id"], "debit": amount, "credit": "0"},
            {"account_id": acc[credit_account]["id"], "debit": "0", "credit": amount},
        ],
    }


def test_seed_chart_creates_accounts(client):
    h, acc = _setup(client, "chart@example.com")
    assert "401" in acc and "701" in acc and "4531" in acc
    assert acc["60"]["is_group"] is True
    assert acc["602"]["is_group"] is False


def test_fiscal_year_creates_12_periods(client):
    h, _ = _setup(client, "fy@example.com")
    r = client.get(f"{API}/fiscal-years", headers=h)
    assert r.status_code == 200
    year = r.json()[0]
    assert len(year["periods"]) == 12
    assert year["periods"][0]["code"] == "2026-01"


def test_create_and_post_entry(client):
    h, acc = _setup(client, "post@example.com")
    r = client.post(f"{API}/journal-entries", headers=h, json=_entry_payload(acc))
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["status"] == "DRAFT"
    assert entry["entry_number"] is None
    eid = entry["id"]

    r = client.post(f"{API}/journal-entries/{eid}/post", headers=h)
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted["status"] == "POSTED"
    assert posted["entry_number"] == 1
    assert posted["posting_date"] is not None


def test_unbalanced_entry_rejected(client):
    h, acc = _setup(client, "unbalanced@example.com")
    payload = _entry_payload(acc)
    payload["lines"][1]["credit"] = "90.00"  # 100 дебит ≠ 90 кредит
    r = client.post(f"{API}/journal-entries", headers=h, json=payload)
    assert r.status_code == 422
    assert "балансирана" in r.json()["detail"]


def test_posting_to_group_account_rejected(client):
    h, acc = _setup(client, "group@example.com")
    payload = _entry_payload(acc, debit_account="60")  # 60 е обобщаваща
    r = client.post(f"{API}/journal-entries", headers=h, json=payload)
    assert r.status_code == 422
    assert "обобщаваща" in r.json()["detail"]


def test_line_both_debit_and_credit_rejected(client):
    h, acc = _setup(client, "bothdc@example.com")
    payload = _entry_payload(acc)
    payload["lines"][0]["credit"] = "5.00"  # ред с дебит и кредit едновременно
    r = client.post(f"{API}/journal-entries", headers=h, json=payload)
    assert r.status_code == 422


def test_entry_without_period_rejected(client):
    h, acc = _setup(client, "noperiod@example.com")
    payload = _entry_payload(acc)
    payload["document_date"] = "2030-03-03"  # няма фискална година 2030
    r = client.post(f"{API}/journal-entries", headers=h, json=payload)
    assert r.status_code == 422
    assert "период" in r.json()["detail"]


def test_min_two_lines_required(client):
    h, acc = _setup(client, "oneline@example.com")
    payload = _entry_payload(acc)
    payload["lines"] = payload["lines"][:1]
    r = client.post(f"{API}/journal-entries", headers=h, json=payload)
    assert r.status_code == 422  # pydantic min_length=2


def test_cannot_post_twice(client):
    h, acc = _setup(client, "twice@example.com")
    eid = client.post(f"{API}/journal-entries", headers=h, json=_entry_payload(acc)).json()["id"]
    assert client.post(f"{API}/journal-entries/{eid}/post", headers=h).status_code == 200
    r = client.post(f"{API}/journal-entries/{eid}/post", headers=h)
    assert r.status_code == 409


def test_reverse_posted_entry(client):
    h, acc = _setup(client, "reverse@example.com")
    eid = client.post(f"{API}/journal-entries", headers=h, json=_entry_payload(acc)).json()["id"]
    client.post(f"{API}/journal-entries/{eid}/post", headers=h)

    r = client.post(f"{API}/journal-entries/{eid}/reverse", headers=h)
    assert r.status_code == 200, r.text
    rev = r.json()
    assert rev["status"] == "REVERSAL"
    assert rev["reverses_entry_id"] == eid
    # редовете са разменени: първоначален дебит 602 → сега кредит 602
    debit_line = next(line for line in rev["lines"] if line["account_id"] == acc["602"]["id"])
    assert float(debit_line["credit"]) == 100.0
    assert float(debit_line["debit"]) == 0.0

    # оригиналът вече е сторниран
    r = client.get(f"{API}/journal-entries/{eid}", headers=h)
    assert r.json()["status"] == "REVERSED"
    # повторно сторно е отказано
    assert client.post(f"{API}/journal-entries/{eid}/reverse", headers=h).status_code == 409


def test_cannot_reverse_draft(client):
    h, acc = _setup(client, "revdraft@example.com")
    eid = client.post(f"{API}/journal-entries", headers=h, json=_entry_payload(acc)).json()["id"]
    r = client.post(f"{API}/journal-entries/{eid}/reverse", headers=h)
    assert r.status_code == 409


def test_posting_blocked_when_period_closed(client):
    h, acc = _setup(client, "closed@example.com")
    # намираме период 2026-07 и го затваряме
    year = client.get(f"{API}/fiscal-years", headers=h).json()[0]
    period_07 = next(p for p in year["periods"] if p["code"] == "2026-07")
    r = client.patch(f"{API}/periods/{period_07['id']}/status", headers=h, json={"status": "CLOSED"})
    assert r.status_code == 200

    eid = client.post(f"{API}/journal-entries", headers=h, json=_entry_payload(acc)).json()["id"]
    r = client.post(f"{API}/journal-entries/{eid}/post", headers=h)
    assert r.status_code == 409
    assert "период" in r.json()["detail"].lower()
