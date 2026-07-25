"""Тестове на PSD2 / open banking пътя (със stub доставчик — без мрежа).

Проверява се това, което носи риск: че тегленето минава през същата дедупликация
като файловия импорт, че изтекло съгласие спира синхронизацията видимо, и че
credentials никога не се връщат по API-то.
"""
import datetime as dt

from tests.conftest import register_and_login

BANK = "/api/v1/banking"


def _setup(client, email):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Акме ЕООД"}).json()["id"]
    h = {**auth, "X-Company-Id": cid}
    account = client.post(f"{BANK}/accounts", headers=h,
                          json={"name": "Разплащателна", "iban": "BG80BNBG96611020345678",
                                "currency": "EUR"}).json()
    return h, account["id"]


def _connect(client, h, account_id, institution="STUB_DSK"):
    conn = client.post(f"{BANK}/connections", headers=h, json={
        "institution_id": institution, "redirect_url": "https://app.example.bg/return",
        "provider": "STUB"}).json()
    remote = client.get(f"{BANK}/connections/{conn['id']}/remote-accounts", headers=h).json()
    client.post(f"{BANK}/connections/{conn['id']}/link-accounts", headers=h,
                json={"mapping": {remote[0]["external_id"]: account_id}})
    return conn, remote


def test_providers_list_does_not_leak_credentials(client):
    h, _ = _setup(client, "ob1@example.com")
    body = client.get(f"{BANK}/providers", headers=h).json()
    text = str(body)
    assert "secret" not in text.lower()
    assert "GOCARDLESS_SECRET" not in text
    codes = {p["code"] for p in body["providers"]}
    assert {"GOCARDLESS", "STUB"} <= codes


def test_stub_is_active_without_credentials(client):
    h, _ = _setup(client, "ob2@example.com")
    body = client.get(f"{BANK}/providers", headers=h).json()
    # Без конфигурирани ключове реалният доставчик не е наличен и се ползва stub.
    assert body["active"] == "STUB"
    live = next(p for p in body["providers"] if p["code"] == "GOCARDLESS")
    assert live["available"] is False


def test_institutions_are_listed(client):
    h, _ = _setup(client, "ob3@example.com")
    rows = client.get(f"{BANK}/institutions?country=BG&provider=STUB", headers=h).json()
    assert rows
    assert all(i["country"] == "BG" for i in rows)


def test_connection_returns_a_consent_link(client):
    h, _ = _setup(client, "ob4@example.com")
    r = client.post(f"{BANK}/connections", headers=h, json={
        "institution_id": "STUB_DSK", "redirect_url": "https://app.example.bg/return",
        "provider": "STUB"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["consent_link"].startswith("https://app.example.bg/return")
    assert body["institution_name"]


def test_linking_accounts_activates_the_connection(client):
    h, account_id = _setup(client, "ob5@example.com")
    conn, remote = _connect(client, h, account_id)

    assert len(remote) == 1
    connections = client.get(f"{BANK}/connections", headers=h).json()
    assert connections[0]["status"] == "ACTIVE"


def test_linking_an_unknown_remote_account_is_refused(client):
    h, account_id = _setup(client, "ob6@example.com")
    conn = client.post(f"{BANK}/connections", headers=h, json={
        "institution_id": "STUB_DSK", "redirect_url": "https://app.example.bg/r",
        "provider": "STUB"}).json()
    r = client.post(f"{BANK}/connections/{conn['id']}/link-accounts", headers=h,
                    json={"mapping": {"няма-такава": account_id}})
    assert r.status_code == 422


def test_sync_imports_transactions(client):
    h, account_id = _setup(client, "ob7@example.com")
    conn, _ = _connect(client, h, account_id)

    r = client.post(f"{BANK}/connections/{conn['id']}/sync?days_back=90", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] > 0
    assert body["accounts"] == 1

    txs = client.get(f"{BANK}/transactions?bank_account_id={account_id}", headers=h).json()
    assert len(txs) == body["imported"]
    assert all(t["status"] == "UNMATCHED" for t in txs)


def test_second_sync_does_not_duplicate(client):
    """Тегленето минава през същата дедупликация като файловия импорт."""
    h, account_id = _setup(client, "ob8@example.com")
    conn, _ = _connect(client, h, account_id)

    first = client.post(f"{BANK}/connections/{conn['id']}/sync?days_back=90", headers=h).json()
    second = client.post(f"{BANK}/connections/{conn['id']}/sync?days_back=90", headers=h).json()

    assert first["imported"] > 0
    assert second["imported"] == 0
    assert second["duplicates"] == first["imported"]

    txs = client.get(f"{BANK}/transactions?bank_account_id={account_id}", headers=h).json()
    assert len(txs) == first["imported"]


def test_sync_without_linked_accounts_is_refused(client):
    h, _ = _setup(client, "ob9@example.com")
    conn = client.post(f"{BANK}/connections", headers=h, json={
        "institution_id": "STUB_DSK", "redirect_url": "https://app.example.bg/r",
        "provider": "STUB"}).json()
    r = client.post(f"{BANK}/connections/{conn['id']}/sync", headers=h)
    assert r.status_code == 422
    assert "свързани сметки" in r.json()["detail"]


def test_expired_consent_blocks_sync_visibly(client):
    """Изтеклото съгласие спира тегленето — но шумно, не тихо."""
    from app.core.database import SessionLocal
    from app.modules.banking.models import BankConnection

    h, account_id = _setup(client, "ob10@example.com")
    conn, _ = _connect(client, h, account_id)

    with SessionLocal() as db:
        row = db.get(BankConnection, __import__("uuid").UUID(conn["id"]))
        row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
        db.commit()

    r = client.post(f"{BANK}/connections/{conn['id']}/sync", headers=h)
    assert r.status_code == 409
    assert "изтече" in r.json()["detail"]

    warnings = client.get(f"{BANK}/consent-warnings", headers=h).json()
    assert any(w["level"] == "ERROR" for w in warnings)


def test_consent_expiring_soon_is_warned(client):
    from app.core.database import SessionLocal
    from app.modules.banking.models import BankConnection

    h, account_id = _setup(client, "ob11@example.com")
    conn, _ = _connect(client, h, account_id)

    with SessionLocal() as db:
        row = db.get(BankConnection, __import__("uuid").UUID(conn["id"]))
        row.expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=3)
        db.commit()

    warnings = client.get(f"{BANK}/consent-warnings", headers=h).json()
    assert any(w["level"] == "WARNING" and "изтича" in w["message"] for w in warnings)


def test_healthy_connection_produces_no_warnings(client):
    h, account_id = _setup(client, "ob12@example.com")
    _connect(client, h, account_id)
    assert client.get(f"{BANK}/consent-warnings", headers=h).json() == []


def test_connections_are_scoped_to_company(client):
    h1, account_id = _setup(client, "ob13@example.com")
    _connect(client, h1, account_id)
    h2, _ = _setup(client, "ob14@example.com")
    assert client.get(f"{BANK}/connections", headers=h2).json() == []


# ------------------------------------------------------------------ нормализация
def test_gocardless_row_mapping():
    """Редът на доставчика се превежда в същия вход, който ползва файловият импорт."""
    from app.modules.banking.connectors.gocardless import _to_transaction

    tx = _to_transaction({
        "transactionId": "TX-1",
        "bookingDate": "2026-03-15",
        "valueDate": "2026-03-16",
        "transactionAmount": {"amount": "-125.40", "currency": "EUR"},
        "creditorName": "Доставчик ООД",
        "creditorAccount": {"iban": "BG80BNBG96611020345678"},
        "remittanceInformationUnstructured": "Плащане по фактура 0000001234",
        "endToEndId": "E2E-77",
    })
    assert tx is not None
    assert str(tx.amount) == "-125.40"
    assert tx.counterparty_name == "Доставчик ООД"
    assert tx.counterparty_iban == "BG80BNBG96611020345678"
    assert tx.reference == "E2E-77"
    assert tx.external_id == "TX-1"


def test_gocardless_row_without_amount_is_skipped():
    from app.modules.banking.connectors.gocardless import _to_transaction

    assert _to_transaction({"bookingDate": "2026-03-15"}) is None
    assert _to_transaction({"transactionAmount": {"amount": "10.00"}}) is None


def test_gocardless_incoming_uses_debtor_side():
    from app.modules.banking.connectors.gocardless import _to_transaction

    tx = _to_transaction({
        "bookingDate": "2026-03-15",
        "transactionAmount": {"amount": "500.00", "currency": "EUR"},
        "debtorName": "Клиент АД",
        "debtorAccount": {"iban": "BG11AAAA11111111111111"},
    })
    assert tx.counterparty_name == "Клиент АД"
    assert tx.counterparty_iban == "BG11AAAA11111111111111"


def test_gocardless_without_credentials_is_not_available():
    from app.modules.banking.connectors.gocardless import GoCardlessBankConnector

    connector = GoCardlessBankConnector()
    assert connector.available is False
    # Достъпът до API-то вдига ясна грешка, а не мълчи.
    try:
        connector.list_institutions("BG")
    except RuntimeError as exc:
        assert "GOCARDLESS_SECRET_ID" in str(exc)
    else:
        raise AssertionError("очаква се RuntimeError без credentials")
