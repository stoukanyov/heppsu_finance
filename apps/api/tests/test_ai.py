from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
DOC = "/api/v1/documents"
AI = "/api/v1/ai"
PDF = b"%PDF-1.4\n%invoice\n"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _post(client, h, acc, dr, cr, amount):
    payload = {
        "document_date": "2026-07-15",
        "lines": [
            {"account_id": acc[dr]["id"], "debit": amount, "credit": "0"},
            {"account_id": acc[cr]["id"], "debit": "0", "credit": amount},
        ],
    }
    eid = client.post(f"{ACC}/journal-entries", headers=h, json=payload).json()["id"]
    client.post(f"{ACC}/journal-entries/{eid}/post", headers=h)


def _upload(client, h):
    return client.post(DOC, headers=h, files={"file": ("faktura.pdf", PDF, "application/pdf")}).json()["id"]


def test_extract_document(client):
    h, _ = _setup(client, "aiextract@example.com")
    doc_id = _upload(client, h)
    r = client.post(f"{AI}/documents/{doc_id}/extract", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["data"]["fields"]["currency"] == "EUR"
    assert body["data"]["overall_confidence"] == 0.62

    # ниска увереност → маркиран за проверка, НЕ осчетоводен
    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["status"] == "NEEDS_REVIEW"


def test_cfo_ask(client):
    h, acc = _setup(client, "aicfo@example.com")
    _post(client, h, acc, "411", "703", "1000.00")   # приход + вземане
    _post(client, h, acc, "503", "411", "1000.00")   # плащане по банка
    _post(client, h, acc, "602", "401", "250.00")    # разход + задължение

    r = client.post(f"{AI}/cfo/ask", headers=h, json={"question": "Как сме финансово?"})
    assert r.status_code == 200, r.text
    body = r.json()
    ctx = body["context"]
    assert float(ctx["cash"]) == 1000.0
    assert float(ctx["revenue"]) == 1000.0
    assert float(ctx["expenses"]) == 250.0
    assert float(ctx["profit"]) == 750.0
    assert float(ctx["payables"]) == 250.0
    assert body["confidence"] in ("low", "medium", "high")
    assert len(body["recommendations"]) >= 1


def test_command_center(client):
    h, acc = _setup(client, "aicc@example.com")
    _post(client, h, acc, "503", "701", "500.00")
    _upload(client, h)  # един необработен документ

    r = client.get(f"{AI}/command-center", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_name"] == "Акме ЕООД"
    assert float(body["cash"]) == 500.0
    assert float(body["revenue"]) == 500.0
    assert body["pending_documents"] == 1
    assert body["summary"]


def test_ai_requires_company(client):
    token = register_and_login(client, "aicompany@example.com")
    r = client.get(f"{AI}/command-center", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400  # липсва X-Company-Id
