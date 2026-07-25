"""Тестове за авто-предложението за осчетоводяване (AI предлага, човек потвърждава)."""
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
DOC = "/api/v1/documents"
AI = "/api/v1/ai"
CP = "/api/v1/counterparties"
PDF = b"%PDF-1.4\n%faktura\n"


def _setup(client, email: str, vat_registered: bool = True, seed: bool = True):
    """Компания със сметкоплан и фискална 2026 г.; връща (headers, code→account)."""
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        "/api/v1/companies",
        headers=auth,
        json={"name": "Акме ЕООД", "is_vat_registered": vat_registered},
    ).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    acc = {}
    if seed:
        acc = {a["code"]: a for a in client.post(f"{ACC}/chart/seed", headers=h).json()}
        client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h, acc


def _upload(client, h, content=PDF, name="faktura.pdf"):
    return client.post(
        DOC, headers=h, files={"file": (name, content, "application/pdf")}
    ).json()["id"]


def _extract(client, h, doc_id):
    r = client.post(f"{AI}/documents/{doc_id}/extract", headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _patch_stub(monkeypatch, fields: dict, overall: float = 0.9) -> None:
    """Заменя детерминирания stub, за да тестваме различни разпознати данни."""
    from app.modules.ai import llm

    def fake(self, content, media_type, filename):  # noqa: ANN001
        return {"fields": fields, "field_confidence": {}, "overall_confidence": overall}

    monkeypatch.setattr(llm.StubLLMClient, "extract_document", fake)


def _by_code(acc: dict, entry: dict) -> dict[str, dict]:
    """Пренарежда редовете на статията по код на сметка."""
    ids = {a["id"]: code for code, a in acc.items()}
    return {ids[line["account_id"]]: line for line in entry["lines"]}


# ============================ Покупка с ДДС ============================
def test_propose_purchase_with_vat(client):
    h, acc = _setup(client, "posting1@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)

    r = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h)
    assert r.status_code == 201, r.text
    body = r.json()

    entry = body["entry"]
    assert entry is not None
    assert entry["status"] == "DRAFT"          # AI НЕ осчетоводява
    assert entry["entry_number"] is None
    assert entry["journal"] == "PURCHASES"
    assert entry["currency"] == "EUR"
    assert float(entry["total_debit"]) == float(entry["total_credit"]) == 120.0

    lines = _by_code(acc, entry)
    assert float(lines["602"]["debit"]) == 100.0   # разходи за външни услуги
    assert float(lines["4531"]["debit"]) == 20.0   # ДДС покупки (данъчен кредит)
    assert float(lines["401"]["credit"]) == 120.0  # доставчици
    assert 0 < body["confidence"] <= 0.62
    assert "602" in body["rationale"]

    # документът е свързан със статията и е в статус PROPOSED
    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["journal_entry_id"] == entry["id"]
    assert doc["status"] == "PROPOSED"

    # човекът потвърждава с вече съществуващия endpoint
    posted = client.post(f"{ACC}/journal-entries/{entry['id']}/post", headers=h)
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "POSTED"


# ============================ Покупка без ДДС ============================
def test_propose_purchase_without_vat(client):
    h, acc = _setup(client, "posting2@example.com", vat_registered=False)
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    entry = body["entry"]
    assert entry is not None
    lines = _by_code(acc, entry)
    assert "4531" not in lines                     # ДДС не се отделя
    assert float(lines["602"]["debit"]) == 120.0   # ДДС влиза в разхода
    assert float(lines["401"]["credit"]) == 120.0
    assert any("не е ДДС регистрирана" in w for w in body["warnings"])


def test_propose_receipt_without_recognized_vat(client, monkeypatch):
    """Касова бележка без разпознат ДДС → само разход срещу доставчик."""
    h, acc = _setup(client, "posting3@example.com")
    _patch_stub(
        monkeypatch,
        {
            "issuer": "Магазин ЕООД",
            "document_number": "0000123",
            "document_date": "2026-03-04",
            "currency": "EUR",
            "total": 45.50,
        },
    )
    doc_id = _upload(client, h, content=b"%PDF-1.4 kasov bon")
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "RECEIPT"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    entry = body["entry"]
    assert entry is not None
    assert entry["document_type"] == "Касова бележка"
    lines = _by_code(acc, entry)
    assert float(lines["602"]["debit"]) == 45.5
    assert float(lines["401"]["credit"]) == 45.5
    assert any("ДДС" in w for w in body["warnings"])


# ============================ Продажба ============================
def test_propose_sale_is_mirrored(client):
    h, acc = _setup(client, "posting4@example.com")
    doc_id = _upload(client, h, content=b"%PDF-1.4 prodazhba")
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_SALE"})
    _extract(client, h, doc_id)

    entry = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()["entry"]
    assert entry is not None and entry["journal"] == "SALES"
    lines = _by_code(acc, entry)
    assert float(lines["411"]["debit"]) == 120.0   # клиенти
    assert float(lines["703"]["credit"]) == 100.0  # приходи от услуги
    assert float(lines["4532"]["credit"]) == 20.0  # ДДС продажби


# ============================ Липсващи данни ============================
def test_propose_without_extraction_returns_none(client):
    h, _ = _setup(client, "posting5@example.com")
    doc_id = _upload(client, h, content=b"%PDF-1.4 bez ocr")

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is None
    assert body["warnings"]
    assert body["confidence"] == 0.0


def test_propose_missing_amount_returns_none(client, monkeypatch):
    h, _ = _setup(client, "posting6@example.com")
    _patch_stub(monkeypatch, {"issuer": "Неясен доставчик", "currency": "EUR"}, overall=0.4)
    doc_id = _upload(client, h, content=b"%PDF-1.4 bez suma")
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is None
    assert any("сума" in w for w in body["warnings"])
    # документът не е пипан — остава за ръчна проверка
    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["journal_entry_id"] is None
    assert doc["status"] != "PROPOSED"


def test_propose_missing_date_returns_none(client, monkeypatch):
    h, _ = _setup(client, "posting7@example.com")
    _patch_stub(monkeypatch, {"total": 60.00, "vat_amount": 10.00, "currency": "EUR"})
    doc_id = _upload(client, h, content=b"%PDF-1.4 bez data")
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is None
    assert any("дата" in w for w in body["warnings"])


def test_propose_without_chart_returns_none(client):
    h, _ = _setup(client, "posting8@example.com", seed=False)
    doc_id = _upload(client, h, content=b"%PDF-1.4 bez smetkoplan")
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is None
    assert any("период" in w.lower() for w in body["warnings"])


def test_propose_closed_period_returns_none(client):
    h, _ = _setup(client, "posting9@example.com")
    fy = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    july = next(p for p in fy["periods"] if p["code"] == "2026-07")
    client.patch(f"{ACC}/periods/{july['id']}/status", headers=h, json={"status": "CLOSED"})

    doc_id = _upload(client, h, content=b"%PDF-1.4 zatvoren period")
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is None
    assert any("CLOSED" in w for w in body["warnings"])


# ============================ Идемпотентност ============================
def test_propose_is_idempotent(client):
    h, _ = _setup(client, "posting10@example.com")
    doc_id = _upload(client, h, content=b"%PDF-1.4 idempotent")
    _extract(client, h, doc_id)

    first = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    second = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()

    assert first["entry"] is not None
    assert second["entry"]["id"] == first["entry"]["id"]
    assert "съществуващата" in second["rationale"]
    # не е създадена втора статия
    entries = client.get(f"{ACC}/journal-entries", headers=h).json()
    assert len(entries) == 1


# ============================ Контрагент ============================
def test_proposal_links_counterparty_by_vat_number(client, monkeypatch):
    h, acc = _setup(client, "posting11@example.com")
    cp_id = client.post(
        CP,
        headers=h,
        json={
            "type": "SUPPLIER",
            "name": "Примерен Доставчик ЕООД",
            "vat_number": "BG203000000",
            "default_account_id": acc["601"]["id"],
        },
    ).json()["id"]

    _patch_stub(
        monkeypatch,
        {
            "issuer": "Примерен Доставчик ЕООД",
            "issuer_vat_number": "BG203000000",
            "document_number": "F-77",
            "document_date": "2026-07-15",
            "currency": "EUR",
            "tax_base": 200.00,
            "vat_amount": 40.00,
            "total": 240.00,
        },
    )
    doc_id = _upload(client, h, content=b"%PDF-1.4 kontragent")
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    entry = body["entry"]
    assert entry is not None
    lines = _by_code(acc, entry)
    assert float(lines["601"]["debit"]) == 200.0   # стандартната сметка на контрагента
    assert float(lines["4531"]["debit"]) == 40.0
    assert float(lines["401"]["credit"]) == 240.0

    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["counterparty_id"] == cp_id


# ============================ Сканиране ============================
def test_scan_returns_posting_proposal(client):
    h, acc = _setup(client, "posting12@example.com")
    r = client.post(
        f"{DOC}/scan",
        headers=h,
        files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0scan-posting", "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["posting"] is not None
    entry = body["posting"]["entry"]
    assert entry["status"] == "DRAFT"
    lines = _by_code(acc, entry)
    assert float(lines["401"]["credit"]) == 120.0
    assert body["document"]["status"] == "PROPOSED"
    assert body["document"]["journal_entry_id"] == entry["id"]


def test_scan_without_chart_still_succeeds(client):
    """Провал на предложението не проваля сканирането."""
    h, _ = _setup(client, "posting13@example.com", seed=False)
    r = client.post(
        f"{DOC}/scan",
        headers=h,
        files={"file": ("scan.jpg", b"\xff\xd8\xff\xe0scan-no-chart", "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["posting"] is None or body["posting"]["entry"] is None
    assert body["extraction"]["data"]["fields"]["currency"] == "EUR"


def test_propose_tenant_isolation(client):
    h_a, _ = _setup(client, "posting-a@example.com")
    doc_id = _upload(client, h_a, content=b"%PDF-1.4 tenant")
    h_b, _ = _setup(client, "posting-b@example.com")
    assert client.post(f"{DOC}/{doc_id}/propose-posting", headers=h_b).status_code == 404


# ============================ AI класификация на разход ============================
def test_classification_recognized_expense(client):
    """Обичаен разход (наем) → признат, пълен данъчен кредит, сметка 602."""
    h, acc = _setup(client, "cls-rent@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Наем на офис за юли"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    cls = body["classification"]
    assert cls is not None
    assert cls["is_deductible"] is True
    assert cls["vat_credit"] == "FULL"
    assert cls["account_code"] == "602"
    assert "признат" in body["rationale"]
    # ДДС се отделя при пълен данъчен кредит
    lines = _by_code(acc, body["entry"])
    assert "4531" in lines


def test_classification_non_deductible_fine(client):
    """Глоба → данъчно НЕПРИЗНАТ разход, без данъчен кредит, сметка 609."""
    h, acc = _setup(client, "cls-fine@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Глоба за просрочено задължение"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    cls = body["classification"]
    assert cls["is_deductible"] is False
    assert cls["vat_credit"] == "NONE"
    assert cls["account_code"] == "609"
    assert "ЗКПО" in cls["tax_rationale"]
    assert any("НЕПРИЗНАТ" in w for w in body["warnings"])
    # без право на кредит → ДДС влиза в разхода, няма ред 4531
    lines = _by_code(acc, body["entry"])
    assert "4531" not in lines
    assert float(lines["609"]["debit"]) == 120.0   # цялата сума в разхода


def test_classification_representation_expenses(client):
    """Представителни разходи → непризнати (данък по чл. 204 ЗКПО), без кредит."""
    h, acc = _setup(client, "cls-repr@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Представителни разходи — бизнес вечеря"})
    _extract(client, h, doc_id)

    cls = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()["classification"]
    assert cls["is_deductible"] is False
    assert cls["vat_credit"] == "NONE"
    assert "204" in cls["tax_rationale"]


def test_classification_fuel_is_materials(client):
    """Гориво → сметка 601 (материали), признат разход."""
    h, acc = _setup(client, "cls-fuel@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Гориво OMV"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    cls = body["classification"]
    assert cls["account_code"] == "601"
    assert cls["is_deductible"] is True
    lines = _by_code(acc, body["entry"])
    assert "601" in lines


def test_classification_receipt_no_vat_credit(client):
    """Касова бележка → признат разход, но БЕЗ данъчен кредит (чл. 71 ЗДДС)."""
    h, acc = _setup(client, "cls-receipt@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "RECEIPT"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    cls = body["classification"]
    assert cls["is_deductible"] is True
    assert cls["vat_credit"] == "NONE"
    lines = _by_code(acc, body["entry"])
    assert "4531" not in lines   # няма данъчен кредит


def test_classification_audit_trail_persisted(client):
    """Класификацията се пази в базата като одитна следа."""
    from sqlalchemy.orm import Session

    from app.core.database import engine
    from app.modules.ai.models import ExpenseClassification

    h, acc = _setup(client, "cls-audit@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Глоба"})
    _extract(client, h, doc_id)
    client.post(f"{DOC}/{doc_id}/propose-posting", headers=h)

    with Session(engine) as db:
        rows = db.query(ExpenseClassification).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.is_deductible is False
        assert row.account_code == "609"
        assert row.tax_rationale
        assert str(row.document_id) == doc_id


def test_no_classification_for_sales(client):
    """Продажбите не се класифицират като разход."""
    h, acc = _setup(client, "cls-sale@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_SALE"})
    _extract(client, h, doc_id)
    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["classification"] is None


# ============================ Авто-осчетоводяване ============================
def test_auto_post_disabled_by_default(client):
    """По подразбиране AI само предлага — статията остава чернова."""
    h, acc = _setup(client, "auto-off@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)
    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["auto_posted"] is False
    assert body["entry"]["status"] == "DRAFT"


def test_auto_post_when_enabled_and_confident(client, monkeypatch):
    """При включена политика и висока увереност статията се осчетоводява автоматично."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTO_POST_DOCUMENTS", True)
    monkeypatch.setattr(settings, "AUTO_POST_MIN_CONFIDENCE", 0.5)

    h, acc = _setup(client, "auto-on@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={
        "doc_type": "INVOICE_PURCHASE", "notes": "Наем на офис"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["auto_posted"] is True
    assert body["entry"]["status"] == "POSTED"
    assert body["entry"]["entry_number"] is not None
    assert "осчетоводена автоматично" in body["rationale"]
    # документът също минава в POSTED
    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["status"] == "POSTED"


def test_auto_post_blocked_below_threshold(client, monkeypatch):
    """Под прага на увереност статията остава чернова, с ясно предупреждение."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTO_POST_DOCUMENTS", True)
    monkeypatch.setattr(settings, "AUTO_POST_MIN_CONFIDENCE", 0.99)

    h, acc = _setup(client, "auto-low@example.com")
    doc_id = _upload(client, h)
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["auto_posted"] is False
    assert body["entry"]["status"] == "DRAFT"
    assert any("под прага" in w for w in body["warnings"])


# ============================ Авто-създаване на контрагент ============================
def test_unknown_counterparty_is_created_and_linked(client, monkeypatch):
    h, _ = _setup(client, "cp-auto1@example.com")
    _patch_stub(
        monkeypatch,
        {
            "issuer": "Нов Доставчик ЕООД",
            "issuer_eik": "205111222",
            "issuer_vat_number": "BG205111222",
            "document_number": "N-1",
            "document_date": "2026-07-15",
            "currency": "EUR",
            "tax_base": 100.00,
            "vat_amount": 20.00,
            "total": 120.00,
        },
    )
    doc_id = _upload(client, h, content=b"%PDF-1.4 nov dostavchik")
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is not None
    assert any(
        "«Нов Доставчик ЕООД» е създаден автоматично" in w for w in body["warnings"]
    ), body["warnings"]

    # контрагентът реално съществува в регистъра, с данни от документа
    cps = client.get(CP, headers=h).json()
    assert len(cps) == 1
    cp = cps[0]
    assert cp["name"] == "Нов Доставчик ЕООД"
    assert cp["eik"] == "205111222"
    assert cp["vat_number"] == "BG205111222"
    assert cp["country"] == "BG"           # изведена от префикса на ДДС номера
    assert cp["type"] == "SUPPLIER"

    # и е закачен за документа
    doc = client.get(f"{DOC}/{doc_id}", headers=h).json()
    assert doc["counterparty_id"] == cp["id"]


def test_second_document_reuses_created_counterparty(client, monkeypatch):
    """Повторно сканиране от същия доставчик не създава втори контрагент."""
    h, _ = _setup(client, "cp-auto2@example.com")
    fields = {
        "issuer": "Повторен Доставчик ООД",
        "issuer_eik": "205333444",
        "issuer_vat_number": "BG205333444",
        "document_number": "P-1",
        "document_date": "2026-07-15",
        "currency": "EUR",
        "tax_base": 50.00,
        "vat_amount": 10.00,
        "total": 60.00,
    }
    _patch_stub(monkeypatch, fields)
    first_doc = _upload(client, h, content=b"%PDF-1.4 povtoren 1")
    _extract(client, h, first_doc)
    first = client.post(f"{DOC}/{first_doc}/propose-posting", headers=h).json()
    assert any("създаден автоматично" in w for w in first["warnings"])

    # втори документ от същия доставчик (различен номер и малка разлика в изписването)
    _patch_stub(monkeypatch, {**fields, "issuer": "ПОВТОРЕН ДОСТАВЧИК ООД.", "document_number": "P-2"})
    second_doc = _upload(client, h, content=b"%PDF-1.4 povtoren 2")
    _extract(client, h, second_doc)
    second = client.post(f"{DOC}/{second_doc}/propose-posting", headers=h).json()
    assert not any("създаден автоматично" in w for w in second["warnings"])

    cps = client.get(CP, headers=h).json()
    assert len(cps) == 1
    assert client.get(f"{DOC}/{second_doc}", headers=h).json()["counterparty_id"] == cps[0]["id"]

    # съвпадението по име също работи, дори без идентификатори в третия документ
    _patch_stub(monkeypatch, {**fields, "issuer_eik": None, "issuer_vat_number": None,
                              "document_number": "P-3"})
    third_doc = _upload(client, h, content=b"%PDF-1.4 povtoren 3")
    _extract(client, h, third_doc)
    client.post(f"{DOC}/{third_doc}/propose-posting", headers=h)
    assert len(client.get(CP, headers=h).json()) == 1


def test_no_counterparty_data_creates_nothing(client, monkeypatch):
    h, _ = _setup(client, "cp-auto3@example.com")
    _patch_stub(
        monkeypatch,
        {
            "document_number": "X-1",
            "document_date": "2026-07-15",
            "currency": "EUR",
            "total": 30.00,
        },
    )
    doc_id = _upload(client, h, content=b"%PDF-1.4 bez kontragent")
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_PURCHASE"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is not None
    assert client.get(CP, headers=h).json() == []
    assert any("няма достатъчно данни за създаване" in w for w in body["warnings"])
    assert client.get(f"{DOC}/{doc_id}", headers=h).json()["counterparty_id"] is None


def test_sale_creates_recipient_not_issuer(client, monkeypatch):
    """При продажба контрагентът е получателят, а не издателят (нашата фирма)."""
    h, _ = _setup(client, "cp-auto4@example.com")
    _patch_stub(
        monkeypatch,
        {
            "issuer": "Акме ЕООД",                 # това сме ние — не се създава
            "issuer_vat_number": "BG111222333",
            "recipient": "Клиент Плюс АД",
            "recipient_vat_number": "DE999888777",
            "document_number": "S-1",
            "document_date": "2026-07-15",
            "currency": "EUR",
            "tax_base": 100.00,
            "vat_amount": 20.00,
            "total": 120.00,
        },
    )
    doc_id = _upload(client, h, content=b"%PDF-1.4 prodazhba kontragent")
    client.patch(f"{DOC}/{doc_id}", headers=h, json={"doc_type": "INVOICE_SALE"})
    _extract(client, h, doc_id)

    body = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert body["entry"] is not None
    cps = client.get(CP, headers=h).json()
    assert len(cps) == 1
    assert cps[0]["name"] == "Клиент Плюс АД"
    assert cps[0]["type"] == "CUSTOMER"
    assert cps[0]["vat_number"] == "DE999888777"
    assert cps[0]["country"] == "DE"       # изведена от префикса на ДДС номера
    assert client.get(f"{DOC}/{doc_id}", headers=h).json()["counterparty_id"] == cps[0]["id"]


# ============================ Файлиране при контрагента ============================
def test_scan_files_document_under_counterparty(client):
    """Мобилен скан създава контрагента и файлира документа в неговото досие."""
    h, _ = _setup(client, "file-cp@example.com")
    r = client.post(
        f"{DOC}/scan", headers=h,
        files={"file": ("skan.jpg", b"\xff\xd8\xff\xe0skan", "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    doc = r.json()["document"]
    assert doc["counterparty_id"] is not None

    # контрагентът е създаден автоматично от разпознатите данни
    cps = client.get(CP, headers=h).json()
    assert any(c["id"] == doc["counterparty_id"] for c in cps)
    cp = next(c for c in cps if c["id"] == doc["counterparty_id"])
    assert cp["type"] == "SUPPLIER"

    # документът е намираем в досието на контрагента
    filed = client.get(f"{DOC}?counterparty_id={cp['id']}", headers=h).json()
    assert [d["id"] for d in filed] == [doc["id"]]


def test_scan_files_document_even_when_posting_fails(client, monkeypatch):
    """Дори когато статия не може да се предложи, сканът се файлира при контрагента."""
    # разпознат е доставчик, но липсва сума → предложението се проваля
    _patch_stub(monkeypatch, {
        "issuer": "Липсваща Сума ЕООД",
        "issuer_vat_number": "BG999888777",
        "currency": "EUR",
    }, overall=0.4)

    h, _ = _setup(client, "file-cp-fail@example.com")
    r = client.post(
        f"{DOC}/scan", headers=h,
        files={"file": ("bez-suma.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    doc = body["document"]

    # статия НЯМА, но контрагентът и връзката съществуват
    assert body["posting"] is None or body["posting"]["entry"] is None
    assert doc["counterparty_id"] is not None
    cps = client.get(CP, headers=h).json()
    cp = next(c for c in cps if c["id"] == doc["counterparty_id"])
    assert cp["vat_number"] == "BG999888777"
    filed = client.get(f"{DOC}?counterparty_id={cp['id']}", headers=h).json()
    assert doc["id"] in [d["id"] for d in filed]


# ---------- Потвърждаване от потребителя (мобилният поток) ----------
def test_confirm_posting_posts_entry_and_advances_document(client, monkeypatch):
    """„Потвърди осчетоводяване": статията става POSTED и документът я догонва."""
    _patch_stub(monkeypatch, {
        "issuer": "Потвърждение ЕООД",
        "issuer_vat_number": "BG111222333",
        "document_number": "F-900",
        "document_date": "2026-03-10",
        "currency": "EUR",
        "tax_base": 500.0,
        "vat_amount": 100.0,
        "total": 600.0,
    })
    h, _ = _setup(client, "confirm-post@example.com")
    doc_id = _upload(client, h)
    _extract(client, h, doc_id)
    proposal = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h).json()
    assert proposal["entry"]["status"] == "DRAFT"

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["entry"]["status"] == "POSTED"
    assert body["entry"]["entry_number"] is not None
    assert body["document"]["status"] == "POSTED"

    # състоянието е трайно, не само в отговора
    assert client.get(f"{DOC}/{doc_id}", headers=h).json()["status"] == "POSTED"


def test_confirm_posting_is_idempotent(client, monkeypatch):
    """Повторно натискане не хвърля и не създава втора статия."""
    _patch_stub(monkeypatch, {
        "issuer": "Двойно Натискане ЕООД",
        "issuer_vat_number": "BG444555666",
        "document_date": "2026-03-11",
        "currency": "EUR",
        "tax_base": 100.0,
        "vat_amount": 20.0,
        "total": 120.0,
    })
    h, _ = _setup(client, "confirm-twice@example.com")
    doc_id = _upload(client, h)
    _extract(client, h, doc_id)
    client.post(f"{DOC}/{doc_id}/propose-posting", headers=h)

    first = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    second = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["entry"]["id"] == second.json()["entry"]["id"]
    assert first.json()["entry"]["entry_number"] == second.json()["entry"]["entry_number"]
    assert len(client.get(f"{ACC}/journal-entries", headers=h).json()) == 1


def test_confirm_posting_without_proposal_is_rejected(client):
    """Документ без предложена статия не може да се потвърди."""
    h, _ = _setup(client, "confirm-none@example.com")
    doc_id = _upload(client, h)

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 409, r.text
    assert "няма предложена" in r.json()["detail"]
