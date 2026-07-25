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


# ============================ Пагинация и търсене ============================
def _upload_many(client, h, count: int, prefix: str = "doc") -> list[str]:
    return [
        _upload(client, h, content=f"%PDF-1.4 {prefix} {i}".encode(), name=f"{prefix}-{i}.pdf")
        .json()["id"]
        for i in range(count)
    ]


def test_list_pagination_and_total_count(client):
    h = _setup(client, "doc-page@example.com")
    _upload_many(client, h, 7, "stranica")

    first = client.get(f"{DOC}?limit=3", headers=h)
    assert first.status_code == 200
    assert len(first.json()) == 3
    assert first.headers["X-Total-Count"] == "7"      # общият брой, не броят на страницата

    second = client.get(f"{DOC}?limit=3&offset=3", headers=h)
    tail = client.get(f"{DOC}?limit=3&offset=6", headers=h)
    assert len(second.json()) == 3
    assert len(tail.json()) == 1
    assert tail.headers["X-Total-Count"] == "7"

    # страниците не се препокриват и заедно покриват всичко
    ids = [d["id"] for d in first.json() + second.json() + tail.json()]
    assert len(set(ids)) == 7

    # отвъд края → празна страница, но верен общ брой
    beyond = client.get(f"{DOC}?limit=3&offset=99", headers=h)
    assert beyond.json() == []
    assert beyond.headers["X-Total-Count"] == "7"


def test_list_default_limit_and_shape(client):
    """Отговорът остава чист списък (без обвивка) — уебът и мобилното разчитат на това."""
    h = _setup(client, "doc-shape@example.com")
    _upload_many(client, h, 2, "forma")
    r = client.get(DOC, headers=h)
    body = r.json()
    assert isinstance(body, list) and len(body) == 2
    assert r.headers["X-Total-Count"] == "2"


def test_limit_over_maximum_is_clipped(client, monkeypatch):
    """limit над максимума се реже, вместо да връща грешка."""
    from app.modules.documents import service as documents_service

    h = _setup(client, "doc-cap@example.com")
    _upload_many(client, h, 4, "tavan")

    monkeypatch.setattr(documents_service, "MAX_PAGE_LIMIT", 2)
    r = client.get(f"{DOC}?limit=1000", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.headers["X-Total-Count"] == "4"


def test_search_by_filename_notes_and_counterparty(client):
    h = _setup(client, "doc-search@example.com")
    cp_id = client.post(
        CP, headers=h, json={"type": "SUPPLIER", "name": "Топлофикация София"}
    ).json()["id"]
    by_file = _upload(client, h, content=b"%PDF-1.4 a", name="naem-yuli.pdf").json()["id"]
    by_note = _upload(client, h, content=b"%PDF-1.4 b", name="scan-002.pdf").json()["id"]
    by_cp = _upload(client, h, content=b"%PDF-1.4 c", name="scan-003.pdf").json()["id"]
    client.patch(f"{DOC}/{by_note}", headers=h, json={"notes": "Гориво за служебния автомобил"})
    client.patch(f"{DOC}/{by_cp}", headers=h, json={"counterparty_id": cp_id})

    # по име на файл, без оглед на регистъра
    found = client.get(f"{DOC}?q=NAEM", headers=h)
    assert [d["id"] for d in found.json()] == [by_file]
    assert found.headers["X-Total-Count"] == "1"

    # по бележки (кирилица, малки букви срещу главна начална)
    assert [d["id"] for d in client.get(f"{DOC}?q=гориво", headers=h).json()] == [by_note]

    # по име на контрагент (join)
    assert [d["id"] for d in client.get(f"{DOC}?q=топлофикация", headers=h).json()] == [by_cp]

    # нищо не съвпада
    empty = client.get(f"{DOC}?q=няма-такъв-документ", headers=h)
    assert empty.json() == [] and empty.headers["X-Total-Count"] == "0"

    # спецсимволите на LIKE не са шаблон
    assert client.get(f"{DOC}?q=%", headers=h).json() == []


def test_search_combines_with_filters_and_pagination(client):
    h = _setup(client, "doc-search-mix@example.com")
    ids = [
        _upload(client, h, content=f"%PDF-1.4 mix {i}".encode(), name=f"faktura-{i}.pdf")
        .json()["id"]
        for i in range(3)
    ]
    other = _upload(client, h, content=b"%PDF-1.4 other", name="dogovor.pdf").json()["id"]
    client.patch(f"{DOC}/{ids[0]}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    client.patch(f"{DOC}/{ids[1]}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    client.patch(f"{DOC}/{other}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})

    r = client.get(f"{DOC}?q=faktura&doc_type=INVOICE_PURCHASE", headers=h)
    assert r.headers["X-Total-Count"] == "2"
    assert {d["id"] for d in r.json()} == {ids[0], ids[1]}

    # търсенето се комбинира и с пагинацията
    page = client.get(f"{DOC}?q=faktura&doc_type=INVOICE_PURCHASE&limit=1", headers=h)
    assert len(page.json()) == 1
    assert page.headers["X-Total-Count"] == "2"

    # и със статуса
    by_status = client.get(f"{DOC}?q=faktura&status=RECEIVED", headers=h)
    assert by_status.headers["X-Total-Count"] == "3"


def test_search_is_tenant_scoped(client):
    h_a = _setup(client, "doc-search-a@example.com")
    _upload(client, h_a, content=b"%PDF-1.4 taen", name="taen-dogovor.pdf")
    h_b = _setup(client, "doc-search-b@example.com")
    r = client.get(f"{DOC}?q=taen", headers=h_b)
    assert r.json() == [] and r.headers["X-Total-Count"] == "0"


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


def test_get_extraction_returns_latest(client, monkeypatch):
    """Клиент, който отваря чужд документ, може да види разпознатото."""
    from tests.test_ai_posting import _extract, _setup, _upload

    h, _ = _setup(client, "get-extraction@example.com")
    doc_id = _upload(client, h)

    # преди разпознаване няма нищо
    empty = client.get(f"{DOC}/{doc_id}/extraction", headers=h)
    assert empty.status_code == 200, empty.text
    assert empty.json() is None

    _extract(client, h, doc_id)
    r = client.get(f"{DOC}/{doc_id}/extraction", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_id"] == doc_id
    assert "fields" in body["data"]


def test_get_extraction_is_tenant_scoped(client):
    """Документ на друга компания не се вижда."""
    from tests.test_ai_posting import _setup, _upload

    h_a, _ = _setup(client, "extraction-owner@example.com")
    doc_id = _upload(client, h_a)

    h_b, _ = _setup(client, "extraction-stranger@example.com")
    r = client.get(f"{DOC}/{doc_id}/extraction", headers=h_b)
    assert r.status_code == 404, r.text
