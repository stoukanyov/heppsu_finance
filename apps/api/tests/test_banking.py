from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
BANK = "/api/v1/banking"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _post_payment(client, h, acc, amount="1000.00", num="INV-1", date="2026-07-15"):
    payload = {
        "document_date": date,
        "document_number": num,
        "lines": [
            {"account_id": acc["503"]["id"], "debit": amount, "credit": "0"},
            {"account_id": acc["411"]["id"], "debit": "0", "credit": amount},
        ],
    }
    eid = client.post(f"{ACC}/journal-entries", headers=h, json=payload).json()["id"]
    client.post(f"{ACC}/journal-entries/{eid}/post", headers=h)
    return eid


def _bank_account(client, h):
    return client.post(f"{BANK}/accounts", headers=h, json={"name": "Разплащателна", "currency": "EUR"}).json()["id"]


def _tx(amount="1000.00", ref="INV-1", date="2026-07-15", ext=None):
    t = {"booking_date": date, "amount": amount, "reference": ref, "description": "плащане"}
    if ext:
        t["external_id"] = ext
    return t


def test_import_and_dedup(client):
    h, _ = _setup(client, "bank1@example.com")
    acc_id = _bank_account(client, h)
    r = client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx(), _tx(ref="INV-2")]})
    assert r.status_code == 201 and r.json() == {"imported": 2, "duplicates": 0}
    # повторен импорт → дубликати
    r = client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx()]})
    assert r.json() == {"imported": 0, "duplicates": 1}


def test_suggest_and_match_full(client):
    h, acc = _setup(client, "bank2@example.com")
    _post_payment(client, h, acc)
    acc_id = _bank_account(client, h)
    client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx()]})
    tx_id = client.get(f"{BANK}/transactions", headers=h).json()[0]["id"]

    sug = client.post(f"{BANK}/transactions/{tx_id}/suggest-matches", headers=h).json()
    assert len(sug) == 1
    assert sug[0]["confidence"] >= 0.9  # точна сума + същата дата + номер в основанието
    assert "точна сума" in sug[0]["reasons"]

    r = client.post(f"{BANK}/transactions/{tx_id}/match", headers=h,
                    json={"journal_entry_id": sug[0]["journal_entry_id"]})
    assert r.status_code == 201, r.text
    tx = client.get(f"{BANK}/transactions/{tx_id}", headers=h).json()
    assert tx["status"] == "MATCHED"
    assert float(tx["matched_amount"]) == 1000.0


def test_amount_mismatch_not_suggested(client):
    h, acc = _setup(client, "bank3@example.com")
    _post_payment(client, h, acc, amount="1000.00")
    acc_id = _bank_account(client, h)
    client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx(amount="999.00")]})
    tx_id = client.get(f"{BANK}/transactions", headers=h).json()[0]["id"]
    sug = client.post(f"{BANK}/transactions/{tx_id}/suggest-matches", headers=h).json()
    assert sug == []


def test_partial_match_over_match_and_unmatch(client):
    h, acc = _setup(client, "bank4@example.com")
    eid = _post_payment(client, h, acc, amount="400.00", num="P-1")
    acc_id = _bank_account(client, h)
    client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx(amount="1000.00", ref="X")]})
    tx_id = client.get(f"{BANK}/transactions", headers=h).json()[0]["id"]

    # частично съпоставяне 400 от 1000
    r = client.post(f"{BANK}/transactions/{tx_id}/match", headers=h,
                    json={"journal_entry_id": eid, "amount": "400.00"})
    assert r.status_code == 201
    match_id = r.json()["id"]
    assert client.get(f"{BANK}/transactions/{tx_id}", headers=h).json()["status"] == "PARTIALLY_MATCHED"

    # опит за над-съпоставяне (още 700 > остатъка 600) → 422
    r = client.post(f"{BANK}/transactions/{tx_id}/match", headers=h,
                    json={"journal_entry_id": eid, "amount": "700.00"})
    assert r.status_code == 422

    # премахване на съпоставянето → обратно UNMATCHED
    r = client.delete(f"{BANK}/transactions/{tx_id}/matches/{match_id}", headers=h)
    assert r.status_code == 204
    assert client.get(f"{BANK}/transactions/{tx_id}", headers=h).json()["status"] == "UNMATCHED"


def test_ignore(client):
    h, _ = _setup(client, "bank5@example.com")
    acc_id = _bank_account(client, h)
    client.post(f"{BANK}/accounts/{acc_id}/import", headers=h, json={"transactions": [_tx(ref="FEE")]})
    tx_id = client.get(f"{BANK}/transactions", headers=h).json()[0]["id"]
    r = client.post(f"{BANK}/transactions/{tx_id}/ignore", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "IGNORED"


def test_tenant_isolation(client):
    h_a, _ = _setup(client, "bank-a@example.com")
    acc_id = _bank_account(client, h_a)
    client.post(f"{BANK}/accounts/{acc_id}/import", headers=h_a, json={"transactions": [_tx()]})
    tx_id = client.get(f"{BANK}/transactions", headers=h_a).json()[0]["id"]

    h_b, _ = _setup(client, "bank-b@example.com")
    assert client.get(f"{BANK}/transactions/{tx_id}", headers=h_b).status_code == 404
