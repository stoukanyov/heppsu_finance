import uuid

from tests.conftest import register_and_login

CP = "/api/v1/counterparties"
PAY = "/api/v1/payments"
IBAN_X = "BG80BNBG96611020345678"
IBAN_Y = "BG18RZBB91550123456789"


def _add_member(company_id: str, user_id: str):
    """Добавя втори член към компанията директно (няма API за членства още)."""
    from app.core.database import SessionLocal
    from app.modules.companies.models import CompanyRole, Membership

    db = SessionLocal()
    db.add(Membership(user_id=uuid.UUID(user_id), company_id=uuid.UUID(company_id), role=CompanyRole.CHIEF_ACCOUNTANT))
    db.commit()
    db.close()


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    company_id = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": company_id}
    supplier = client.post(CP, headers=h, json={
        "type": "SUPPLIER", "name": "Доставчик ЕООД",
        "bank_accounts": [{"iban": IBAN_X, "is_primary": True}],
    }).json()["id"]
    return h, company_id, supplier


def test_prepare_with_risk_flags(client):
    h, _, supplier = _setup(client, "pay1@example.com")
    r = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "6000.00", "recipient_iban": IBAN_Y})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "PREPARED"
    assert "IBAN_MISMATCH" in p["risk_flags"]
    assert "HIGH_VALUE" in p["risk_flags"]
    # известният IBAN не вдига флаг
    r2 = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "100.00", "recipient_iban": IBAN_X})
    assert "IBAN_MISMATCH" not in r2.json()["risk_flags"]


def test_cannot_approve_own(client):
    h, _, supplier = _setup(client, "pay2@example.com")
    pid = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "100.00"}).json()["id"]
    r = client.post(f"{PAY}/{pid}/approve", headers=h)
    assert r.status_code == 403
    assert "собственото" in r.json()["detail"]


def test_checker_approves(client):
    h, company_id, supplier = _setup(client, "pay-maker@example.com")
    pid = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "250.00"}).json()["id"]

    # втори потребител (checker), добавен като член на компанията
    token_b = register_and_login(client, "pay-checker@example.com")
    auth_b = {"Authorization": f"Bearer {token_b}"}
    me_b = client.get("/api/v1/auth/me", headers=auth_b).json()
    _add_member(company_id, me_b["id"])
    h_b = {**auth_b, "X-Company-Id": company_id}

    r = client.post(f"{PAY}/{pid}/approve", headers=h_b)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    assert r.json()["approved_by_id"] == me_b["id"]


def test_reject(client):
    h, _, supplier = _setup(client, "pay3@example.com")
    pid = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "100.00"}).json()["id"]
    r = client.post(f"{PAY}/{pid}/reject", headers=h, json={"reason": "грешен IBAN"})
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED" and r.json()["rejection_reason"] == "грешен IBAN"


def test_non_supplier_rejected(client):
    h, _, _ = _setup(client, "pay4@example.com")
    customer = client.post(CP, headers=h, json={"type": "CUSTOMER", "name": "Клиент"}).json()["id"]
    r = client.post(PAY, headers=h, json={"counterparty_id": customer, "amount": "100.00"})
    assert r.status_code == 422 and "доставчик" in r.json()["detail"]


def test_approve_requires_prepared(client):
    h, company_id, supplier = _setup(client, "pay5@example.com")
    pid = client.post(PAY, headers=h, json={"counterparty_id": supplier, "amount": "100.00"}).json()["id"]
    client.post(f"{PAY}/{pid}/cancel", headers=h)
    r = client.post(f"{PAY}/{pid}/approve", headers=h)
    assert r.status_code == 409
