"""Тестове за подаванията към НАП.

Проверяват целия реалистичен поток: изчисление → валидации → пакет → ръчно подаване
с КЕП (извън системата) → импорт на разписката. Системата НЕ подава сама.
"""
import io
import zipfile

from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
VAT = "/api/v1/vat"
SUB = "/api/v1/submissions"


def _setup(client, email: str, vat_registered: bool = True, eik: str | None = "208418861"):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    body = {"name": "Хепсу Консултинг ЕООД", "is_vat_registered": vat_registered}
    if eik:
        body.update({"eik": eik, "vat_number": "BG" + eik})
    cid = client.post("/api/v1/companies", headers=auth, json=body).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    codes = {c["code"]: c for c in client.post(f"{VAT}/codes/seed", headers=h).json()}
    return h, codes


def _period(client, h, code="2026-07"):
    year = client.get(f"{ACC}/fiscal-years", headers=h).json()[0]
    return next(p["id"] for p in year["periods"] if p["code"] == code)


def _entry(client, h, code_id, base, doc, vat_no=None, date="2026-07-10"):
    payload = {"vat_code_id": code_id, "document_date": date, "document_number": doc,
               "counterparty_name": "Контрагент", "tax_base": base}
    if vat_no:
        payload["counterparty_vat_number"] = vat_no
    assert client.post(f"{VAT}/entries", headers=h, json=payload).status_code == 201


# ============================ Провайдъри ============================
def test_providers_listed_with_capabilities(client):
    h, _ = _setup(client, "sub-prov@example.com")
    r = client.get(f"{SUB}/providers", headers=h).json()
    assert r["active"] == "NRA_PORTAL_PACKAGE"
    by_code = {p["code"]: p for p in r["providers"]}
    # днес наличен е само пакетът за ръчно подаване
    assert by_code["NRA_PORTAL_PACKAGE"]["available"] is True
    assert by_code["NRA_PORTAL_PACKAGE"]["electronic_submission"] is False
    # бъдещите API провайдъри са регистрирани, но не активни
    assert {"NRA_VAT_API", "NRA_SAFT_API", "NRA_SOCIAL_API"} <= set(by_code)
    assert by_code["NRA_VAT_API"]["available"] is False


def test_future_provider_refuses_to_submit(client):
    """Бъдещият API провайдър вдига ясна грешка, докато НАП не публикува спецификация."""
    from app.tax_engine.submission.base import SubmissionPackage
    from app.tax_engine.submission.providers import NraVatApiProvider

    provider = NraVatApiProvider()
    assert provider.supports_electronic_submission is True
    try:
        provider.submit(None, SubmissionPackage(filename="x.zip", content=b""))
        raise AssertionError("трябваше да вдигне NotImplementedError")
    except NotImplementedError as exc:
        assert "спецификация" in str(exc)


# ============================ Преглед (стъпки 1–3) ============================
def test_preview_lists_package_contents_and_controls(client):
    h, codes = _setup(client, "sub-prev@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "5000.00", "S-1")
    _entry(client, h, codes["P20"]["id"], "1000.00", "P-1")

    r = client.get(f"{SUB}/vat/{pid}/preview", headers=h)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["period_code"] == "2026-07"
    assert pv["provider_code"] == "NRA_PORTAL_PACKAGE"
    assert pv["supports_electronic_submission"] is False
    assert pv["portal_url"]
    # трите задължителни файла, без VIES (няма ВОД)
    joined = " ".join(pv["package_contents"])
    assert "DEKLAR.TXT" in joined and "PRODAGBI.TXT" in joined and "POKUPKI.TXT" in joined
    assert "VIES" not in joined
    assert pv["has_blocking_errors"] is False
    assert pv["submission_deadline"] == "2026-08-14"
    assert float(pv["summary"]["cell_20"]) == 1000.0    # начислен ДДС 20% от 5000
    assert float(pv["summary"]["cell_50"]) == 800.0     # 1000 − 200 кредит


def test_preview_includes_vies_when_ics_present(client):
    h, codes = _setup(client, "sub-vies@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["SICS"]["id"], "3000.00", "V-1", vat_no="DE111222333")
    pv = client.get(f"{SUB}/vat/{pid}/preview", headers=h).json()
    assert any("VIES" in c for c in pv["package_contents"])


def test_preview_blocks_when_not_vat_registered(client):
    h, codes = _setup(client, "sub-novat@example.com", vat_registered=False)
    pid = _period(client, h)
    pv = client.get(f"{SUB}/vat/{pid}/preview", headers=h).json()
    assert pv["has_blocking_errors"] is True
    assert any(c["code"] == "NOT_VAT_REGISTERED" for c in pv["controls"])


# ============================ Подготовка на пакета (стъпки 4–5) ============================
def test_prepare_package_creates_zip_with_all_files(client):
    h, codes = _setup(client, "sub-prep@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "5000.00", "S-1")
    _entry(client, h, codes["SICS"]["id"], "2000.00", "V-1", vat_no="DE111222333")
    _entry(client, h, codes["P20"]["id"], "1000.00", "P-1")

    r = client.post(f"{SUB}/vat/{pid}/prepare", headers=h)
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["status"] == "PREPARED"
    assert sub["kind"] == "VAT_RETURN"
    assert sub["provider_code"] == "NRA_PORTAL_PACKAGE"
    assert sub["package_filename"].startswith("NAP-DDS-BG208418861-2026-07")
    assert len(sub["package_sha256"]) == 64
    assert sub["package_size"] > 0
    assert sub["submission_deadline"] == "2026-08-14"

    # пакетът се сваля и съдържа всички файлове
    dl = client.get(f"{SUB}/{sub['id']}/package", headers=h)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"
    names = set(zipfile.ZipFile(io.BytesIO(dl.content)).namelist())
    assert {"DEKLAR.TXT", "PRODAGBI.TXT", "POKUPKI.TXT", "VIES.TXT"} <= names
    # изтеглянето отбелязва статуса
    assert client.get(f"{SUB}/{sub['id']}", headers=h).json()["status"] == "DOWNLOADED"


def test_prepare_blocked_by_errors(client):
    h, codes = _setup(client, "sub-block@example.com", vat_registered=False)
    pid = _period(client, h)
    r = client.post(f"{SUB}/vat/{pid}/prepare", headers=h)
    assert r.status_code == 422
    assert "блокиращи грешки" in r.json()["detail"]


def test_prepare_blocked_without_identifier(client):
    h, codes = _setup(client, "sub-noid@example.com", eik=None)
    pid = _period(client, h)
    r = client.post(f"{SUB}/vat/{pid}/prepare", headers=h)
    assert r.status_code == 422
    assert "ЕИК" in r.json()["detail"]


def test_package_is_stored_as_document(client):
    """Пакетът се пази като документ — проследим при проверка от НАП."""
    h, codes = _setup(client, "sub-doc@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "1000.00", "S-1")
    client.post(f"{SUB}/vat/{pid}/prepare", headers=h)
    docs = client.get("/api/v1/documents", headers=h).json()
    assert any(d["original_filename"].startswith("NAP-DDS-") for d in docs)


# ============================ Ръчно подаване и разписка (стъпки 6–7) ============================
def test_mark_submitted_then_import_receipt(client):
    h, codes = _setup(client, "sub-receipt@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "5000.00", "S-1")
    sub_id = client.post(f"{SUB}/vat/{pid}/prepare", headers=h).json()["id"]

    # стъпка 6: подадено в портала с КЕП (извън системата)
    sub = client.post(
        f"{SUB}/{sub_id}/mark-submitted", headers=h,
        json={"submitted_at": "2026-08-12", "notes": "Подадено с КЕП от управителя"},
    ).json()
    assert sub["status"] == "SUBMITTED_EXTERNALLY"
    assert sub["submitted_at"] == "2026-08-12"

    # стъпка 7: разписката се импортира и съхранява
    r = client.post(
        f"{SUB}/{sub_id}/receipt", headers=h,
        files={"file": ("razpiska.pdf", b"%PDF-1.4 razpiska NAP", "application/pdf")},
        data={"receipt_number": "1234567890", "receipt_date": "2026-08-12", "accepted": "true"},
    )
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["status"] == "ACCEPTED"
    assert sub["receipt_number"] == "1234567890"
    assert sub["receipt_date"] == "2026-08-12"
    assert sub["receipt_document_id"] is not None
    # самата разписка е свалима като документ
    dl = client.get(f"/api/v1/documents/{sub['receipt_document_id']}/file", headers=h)
    assert dl.status_code == 200 and b"razpiska" in dl.content


def test_receipt_import_without_marking_submitted(client):
    """Импортът на разписка сам отбелязва подаването — не се иска ръчна стъпка."""
    h, codes = _setup(client, "sub-auto@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "1000.00", "S-1")
    sub_id = client.post(f"{SUB}/vat/{pid}/prepare", headers=h).json()["id"]
    sub = client.post(
        f"{SUB}/{sub_id}/receipt", headers=h,
        files={"file": ("p.pdf", b"%PDF-1.4 protokol", "application/pdf")},
        data={"receipt_number": "999", "accepted": "true"},
    ).json()
    assert sub["status"] == "ACCEPTED"
    assert sub["submitted_at"] is not None


def test_rejected_receipt_allows_new_attempt(client):
    h, codes = _setup(client, "sub-reject@example.com")
    pid = _period(client, h)
    _entry(client, h, codes["S20"]["id"], "1000.00", "S-1")
    sub_id = client.post(f"{SUB}/vat/{pid}/prepare", headers=h).json()["id"]
    sub = client.post(
        f"{SUB}/{sub_id}/receipt", headers=h,
        files={"file": ("otkaz.pdf", b"%PDF-1.4 otkaz", "application/pdf")},
        data={"accepted": "false", "notes": "Отхвърлена — невалиден формат"},
    ).json()
    assert sub["status"] == "REJECTED"
    assert "невалиден" in sub["notes"]
    # може да се подготви нов пакет за същия период
    assert client.post(f"{SUB}/vat/{pid}/prepare", headers=h).status_code == 201


def test_submissions_listed_and_tenant_isolated(client):
    h_a, codes_a = _setup(client, "sub-iso-a@example.com")
    pid = _period(client, h_a)
    _entry(client, h_a, codes_a["S20"]["id"], "1000.00", "S-1")
    client.post(f"{SUB}/vat/{pid}/prepare", headers=h_a)
    assert len(client.get(SUB, headers=h_a).json()) == 1

    h_b, _ = _setup(client, "sub-iso-b@example.com")
    assert client.get(SUB, headers=h_b).json() == []
