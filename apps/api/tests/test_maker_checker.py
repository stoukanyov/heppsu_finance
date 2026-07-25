"""Тестове за maker-checker („четири очи“) при осчетоводяване на документи.

Правилото: качилият документа не може сам да го одобри/осчетоводи. Изключено е по
подразбиране (първият клиент е фирма с един човек) и се включва за всяка компания
поотделно през `PATCH /companies/current {"maker_checker_enabled": true}`.
"""
from tests.conftest import register_and_login

ACC = "/api/v1/accounting"
AI = "/api/v1/ai"
COMPANIES = "/api/v1/companies"
DOC = "/api/v1/documents"
MEM = "/api/v1/members"
PDF = b"%PDF-1.4\n%faktura\n"


def _setup(client, email: str):
    """Компания със сметкоплан и фискална година; връща headers на собственика."""
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post(
        COMPANIES, headers=auth, json={"name": "Акме ЕООД", "is_vat_registered": True}
    ).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    client.post(f"{ACC}/chart/seed", headers=h)
    client.post(f"{ACC}/fiscal-years", headers=h, json={"year": 2026})
    return h


def _add_accountant(client, owner_h, email: str) -> dict:
    """Втори потребител в същата компания с роля ACCOUNTANT (има documents.approve)."""
    token = register_and_login(client, email)
    r = client.post(MEM, headers=owner_h, json={"email": email, "role": "ACCOUNTANT"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {token}", "X-Company-Id": owner_h["X-Company-Id"]}


def _proposed_document(client, h) -> str:
    """Качва документ, разпознава го и му предлага счетоводна статия (DRAFT)."""
    doc_id = client.post(
        DOC, headers=h, files={"file": ("faktura.pdf", PDF, "application/pdf")}
    ).json()["id"]
    assert client.post(f"{AI}/documents/{doc_id}/extract", headers=h).status_code == 201
    r = client.post(f"{DOC}/{doc_id}/propose-posting", headers=h)
    assert r.status_code == 201, r.text
    return doc_id


def _enable(client, h, enabled: bool | None = True):
    r = client.patch(COMPANIES + "/current", headers=h, json={"maker_checker_enabled": enabled})
    assert r.status_code == 200, r.text
    return r.json()


# ============================ Изключено по подразбиране ============================
def test_disabled_by_default_owner_posts_own_document(client):
    """Без изрична настройка нищо не се променя — фирмата с един човек работи."""
    h = _setup(client, "mc-default@example.com")
    doc_id = _proposed_document(client, h)

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["document"]["status"] == "POSTED"


def test_default_company_setting_is_unset(client):
    """`None` означава „компанията не е решавала“ → важи глобалната стойност."""
    h = _setup(client, "mc-unset@example.com")
    assert client.get(COMPANIES + "/current", headers=h).json()["maker_checker_enabled"] is None


# ============================ Включено за компанията ============================
def test_maker_cannot_post_own_document(client):
    h = _setup(client, "mc-maker@example.com")
    _add_accountant(client, h, "mc-checker@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["code"] == "MAKER_CHECKER_VIOLATION"
    assert body["required_permission"] == "documents.approve"
    assert "четири очи" in body["detail"]
    # съобщението казва КОЙ трябва да одобри
    assert "mc-checker@example.com" in body["detail"] or "Тест" in body["detail"]

    # документът не е мръднал
    assert client.get(f"{DOC}/{doc_id}", headers=h).json()["status"] == "PROPOSED"


def test_another_user_with_permission_can_post(client):
    h = _setup(client, "mc-maker2@example.com")
    checker_h = _add_accountant(client, h, "mc-checker2@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=checker_h)
    assert r.status_code == 200, r.text
    assert r.json()["document"]["status"] == "POSTED"
    assert r.json()["entry"]["status"] == "POSTED"


def test_maker_cannot_approve_own_document_via_status(client):
    """Правилото важи и за прекия преход PROPOSED → APPROVED (мобилният екран)."""
    h = _setup(client, "mc-status@example.com")
    _add_accountant(client, h, "mc-status-checker@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.patch(f"{DOC}/{doc_id}/status", headers=h, json={"status": "APPROVED"})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "MAKER_CHECKER_VIOLATION"


def test_checker_can_approve_via_status(client):
    h = _setup(client, "mc-status-ok@example.com")
    checker_h = _add_accountant(client, h, "mc-status-ok2@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.patch(f"{DOC}/{doc_id}/status", headers=checker_h, json={"status": "APPROVED"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"


def test_returning_own_document_is_still_allowed(client):
    """Връщането за корекция не е одобрение — то остава позволено за качилия."""
    h = _setup(client, "mc-return@example.com")
    _add_accountant(client, h, "mc-return-checker@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.patch(f"{DOC}/{doc_id}/status", headers=h, json={"status": "RETURNED"})
    assert r.status_code == 200, r.text


def test_message_explains_when_nobody_else_can_approve(client):
    """Фирма с един човек, която включи правилото, получава смислен изход."""
    h = _setup(client, "mc-alone@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h)

    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 403, r.text
    assert "няма друг човек" in r.json()["detail"]


def test_disabling_again_restores_the_old_behaviour(client):
    h = _setup(client, "mc-toggle@example.com")
    doc_id = _proposed_document(client, h)

    _enable(client, h, True)
    assert client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h).status_code == 403

    _enable(client, h, False)
    assert client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h).status_code == 200


# ============================ Глобална стойност по подразбиране ============================
def test_global_default_applies_to_companies_without_own_setting(client, monkeypatch):
    """Компания с NULL наследява глобалното `MAKER_CHECKER_ENABLED`."""
    from app.core.config import settings

    h = _setup(client, "mc-global@example.com")
    _add_accountant(client, h, "mc-global-checker@example.com")
    doc_id = _proposed_document(client, h)

    monkeypatch.setattr(settings, "MAKER_CHECKER_ENABLED", True)
    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 403, r.text


def test_company_setting_overrides_the_global_one(client, monkeypatch):
    """Изричното решение на компанията бие глобалната политика."""
    from app.core.config import settings

    h = _setup(client, "mc-override@example.com")
    doc_id = _proposed_document(client, h)
    _enable(client, h, False)

    monkeypatch.setattr(settings, "MAKER_CHECKER_ENABLED", True)
    r = client.post(f"{DOC}/{doc_id}/confirm-posting", headers=h)
    assert r.status_code == 200, r.text
