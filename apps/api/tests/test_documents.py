from tests.conftest import register_and_login

DOC = "/api/v1/documents"
CP = "/api/v1/counterparties"

PDF_BYTES = b"%PDF-1.4\n%test invoice content\n"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    return {**auth, "X-Company-Id": company_id}


def _upload(client, h, content=PDF_BYTES, name="faktura.pdf", ctype="application/pdf"):
    return client.post(DOC, headers=h, files={"file": (name, content, ctype)})


def test_upload_document(client):
    h = _setup(client, "doc1@example.com")
    r = _upload(client, h)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "RECEIVED"
    assert doc["size_bytes"] == len(PDF_BYTES)
    assert len(doc["sha256"]) == 64
    assert doc["duplicate_of_id"] is None


def test_upload_unsupported_type_rejected(client):
    h = _setup(client, "doc2@example.com")
    r = _upload(client, h, content=b"hello", name="note.txt", ctype="text/plain")
    assert r.status_code == 415


def test_duplicate_detection(client):
    h = _setup(client, "doc3@example.com")
    first = _upload(client, h).json()
    second = _upload(client, h).json()
    assert second["status"] == "POTENTIAL_DUPLICATE"
    assert second["duplicate_of_id"] == first["id"]


def test_list_and_filter(client):
    h = _setup(client, "doc4@example.com")
    _upload(client, h, content=b"%PDF-1.4 one")
    _upload(client, h, content=b"%PDF-1.4 two")
    all_docs = client.get(DOC, headers=h).json()
    assert len(all_docs) == 2
    received = client.get(f"{DOC}?status=RECEIVED", headers=h).json()
    assert len(received) == 2


def test_download_file(client):
    h = _setup(client, "doc5@example.com")
    doc_id = _upload(client, h).json()["id"]
    r = client.get(f"{DOC}/{doc_id}/file", headers=h)
    assert r.status_code == 200
    assert r.content == PDF_BYTES
    assert r.headers["content-type"].startswith("application/pdf")


def test_valid_status_transition(client):
    h = _setup(client, "doc6@example.com")
    doc_id = _upload(client, h).json()["id"]
    r = client.patch(f"{DOC}/{doc_id}/status", headers=h, json={"status": "NEEDS_REVIEW"})
    assert r.status_code == 200 and r.json()["status"] == "NEEDS_REVIEW"


def test_invalid_status_transition(client):
    h = _setup(client, "doc7@example.com")
    doc_id = _upload(client, h).json()["id"]
    # RECEIVED → POSTED не е позволено
    r = client.patch(f"{DOC}/{doc_id}/status", headers=h, json={"status": "POSTED"})
    assert r.status_code == 409


def test_update_metadata_with_counterparty(client):
    h = _setup(client, "doc8@example.com")
    cp_id = client.post(CP, headers=h, json={"type": "SUPPLIER", "name": "Доставчик"}).json()["id"]
    doc_id = _upload(client, h).json()["id"]
    r = client.patch(
        f"{DOC}/{doc_id}",
        headers=h,
        json={"doc_type": "INVOICE_PURCHASE", "counterparty_id": cp_id, "notes": "юли"},
    )
    assert r.status_code == 200
    assert r.json()["doc_type"] == "INVOICE_PURCHASE"
    assert r.json()["counterparty_id"] == cp_id


def test_update_metadata_invalid_counterparty(client):
    h = _setup(client, "doc9@example.com")
    doc_id = _upload(client, h).json()["id"]
    r = client.patch(
        f"{DOC}/{doc_id}",
        headers=h,
        json={"counterparty_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 422


def test_tenant_isolation(client):
    h_a = _setup(client, "doc-a@example.com")
    doc_id = _upload(client, h_a).json()["id"]
    h_b = _setup(client, "doc-b@example.com")
    assert client.get(f"{DOC}/{doc_id}", headers=h_b).status_code == 404
    assert client.get(f"{DOC}/{doc_id}/file", headers=h_b).status_code == 404


def test_mobile_scan_uploads_and_ocrs(client):
    h = _setup(client, "scan1@example.com")
    r = client.post(
        f"{DOC}/scan",
        headers=h,
        files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0scanbytes", "image/jpeg")},
        data={"note": "мобилен скан"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # запазено е и изображението (документ със source=MOBILE), и данните (extraction)
    assert body["document"]["source"] == "MOBILE"
    assert body["document"]["notes"] == "мобилен скан"
    assert body["document"]["status"] in ("RECOGNIZED", "NEEDS_REVIEW")
    assert body["extraction"]["document_id"] == body["document"]["id"]
    assert "fields" in body["extraction"]["data"]
    # оригиналът се сваля обратно
    dl = client.get(f"{DOC}/{body['document']['id']}/file", headers=h)
    assert dl.status_code == 200
    assert dl.content == b"\xff\xd8\xff\xe0scanbytes"
