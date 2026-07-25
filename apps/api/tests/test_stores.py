"""Тестове за модул „Магазини" (App Store / Google Play) — през stub конектора."""
from tests.conftest import register_and_login

ST = "/api/v1/stores"


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Heppsu ООД"}).json()["id"]
    return {**auth, "X-Company-Id": cid}


def test_status_is_stub_without_credentials(client):
    h = _setup(client, "st-status@example.com")
    s = client.get(f"{ST}/status", headers=h).json()
    assert s["provider"] == "stub"
    assert s["apple_configured"] is False


def test_sync_and_dedup(client):
    h = _setup(client, "st-sync@example.com")
    q = "date_from=2026-06-01&date_to=2026-06-07"
    r = client.post(f"{ST}/APP_STORE/sync?{q}", headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["platform"] == "APP_STORE"
    assert res["imported"] > 0 and res["duplicates"] == 0
    first_imported = res["imported"]
    # повторно синхронизиране → всичко е дубликат
    r2 = client.post(f"{ST}/APP_STORE/sync?{q}", headers=h).json()
    assert r2["imported"] == 0 and r2["duplicates"] == first_imported


def test_analytics_top_app_and_country(client):
    h = _setup(client, "st-an@example.com")
    q = "date_from=2026-06-01&date_to=2026-06-10"
    client.post(f"{ST}/APP_STORE/sync?{q}", headers=h)
    client.post(f"{ST}/GOOGLE_PLAY/sync?{q}", headers=h)
    a = client.get(f"{ST}/analytics", headers=h).json()
    assert a["total_units"] > 0
    assert float(a["total_proceeds"]) > 0
    assert a["top_app"] is not None
    assert a["top_country"] is not None
    # има разбивка по двата магазина
    platforms = {p["key"] for p in a["by_platform"]}
    assert "App Store" in platforms and "Google Play" in platforms
    # by_app подредено низходящо по приходи
    proceeds = [float(x["proceeds"]) for x in a["by_app"]]
    assert proceeds == sorted(proceeds, reverse=True)


def test_analytics_platform_filter(client):
    h = _setup(client, "st-filter@example.com")
    q = "date_from=2026-06-01&date_to=2026-06-05"
    client.post(f"{ST}/APP_STORE/sync?{q}", headers=h)
    client.post(f"{ST}/GOOGLE_PLAY/sync?{q}", headers=h)
    a = client.get(f"{ST}/analytics?platform=GOOGLE_PLAY", headers=h).json()
    assert {p["key"] for p in a["by_platform"]} == {"Google Play"}


def test_googleplay_csv_parser():
    """Реалният Google Play конектор парсва CSV коректно (без мрежа)."""
    from app.modules.stores.connectors.googleplay import GooglePlayConnector

    csv_text = (
        "Transaction Date,Product Title,Product id,Buyer Country,Quantity,"
        "Amount (Merchant Currency),Currency of Sale,Product Type\n"
        "2026-06-15,Heppsu Pro,com.heppsu.pro,DE,2,17.98,EUR,Subscription\n"
    )
    rows = GooglePlayConnector().parse_csv(csv_text)
    assert len(rows) == 1
    r = rows[0]
    assert r.app_identifier == "com.heppsu.pro"
    assert r.country == "DE"
    assert str(r.proceeds) == "17.98"
    assert r.product_type.value == "SUBSCRIPTION"
