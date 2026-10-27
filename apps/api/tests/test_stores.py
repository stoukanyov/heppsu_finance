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




# ---------------------------------------------------------------------------
# Какво се случи на 26.10.2026: екранът „Магазини“ в production показваше 1305
# реда продажби на `com.heppsu.invoice`, `com.heppsu.pro` и `com.heppsu.scan` —
# приложения, които не съществуват — и общо ~28 800 приход. Всичко идваше от
# подставения конектор, защото режимът „auto“ падаше към него при липса на
# ключове. В счетоводна система това не е „демо“, а неверни данни.
#
# Тестовете долу покриват всяка от намерените причини и НЕ МИНАВАТ върху стария
# код.
# ---------------------------------------------------------------------------
import datetime as dt
import pathlib
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.modules.stores.models import StorePlatform


def _nastroiki(**kw) -> Settings:
    bazovi = {"SECRET_KEY": "x" * 40, "ENVIRONMENT": "test"}
    return Settings(**{**bazovi, **kw})


def test_auto_bez_klyuchove_ne_vrushta_podstaveni_danni():
    """„auto“ значи „реални, ако има ключове“ — не „измисли числа“."""
    s = _nastroiki(STORE_PROVIDER="auto")
    assert s.store_provider_for("APP_STORE") == "off"
    assert s.store_provider_for("GOOGLE_PLAY") == "off"


def test_rezhimut_e_na_magazin_a_ne_obsht(tmp_path):
    """С ключ само за Apple, Google Play НЕ е „live“.

    Старото правило беше `live if (has_apple or has_google)`: синхронизирането
    на Google Play тръгваше към реалния конектор само защото Apple има ключ, и
    се чупеше вътре в него.

    Ключът е истински файл: дотогава тестът ползваше несъществуващия
    „/tmp/k.p8“ и беше зелен точно върху дефекта от 27.10.2026 — зададен път
    без файл се броеше за свързан магазин.
    """
    klyuch = tmp_path / "AuthKey_TEST.p8"
    klyuch.write_text("-----BEGIN PRIVATE KEY-----\nproba\n-----END PRIVATE KEY-----\n")
    s = _nastroiki(
        STORE_PROVIDER="auto",
        APPLE_ISSUER_ID="iss", APPLE_KEY_ID="kid", APPLE_PRIVATE_KEY_PATH=str(klyuch),
        APPLE_VENDOR_NUMBER="87654321",
    )
    assert s.store_provider_for("APP_STORE") == "live"
    assert s.store_provider_for("GOOGLE_PLAY") == "off"
    assert s.apple_configured is True
    assert s.google_play_configured is False


def test_production_ne_pokazva_podstaveni_danni_dori_izrichno():
    """В production `STORE_PROVIDER=stub` не включва подставените данни."""
    assert _nastroiki(STORE_PROVIDER="stub", ENVIRONMENT="production").store_provider_for(
        "APP_STORE"
    ) == "off"
    # Демо средата е „staging“ и нарочно си остава с показни данни.
    assert _nastroiki(STORE_PROVIDER="stub", ENVIRONMENT="staging").store_provider_for(
        "APP_STORE"
    ) == "stub"


def test_nesvurzan_magazin_dava_greshka_a_ne_konektor(monkeypatch):
    from app.modules.stores.connectors import factory
    from app.modules.stores.connectors.factory import StoreNotConnected, get_connector

    monkeypatch.setattr(factory.settings, "STORE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(factory.settings, "APPLE_ISSUER_ID", "", raising=False)
    with pytest.raises(StoreNotConnected) as exc:
        get_connector(StorePlatform.APP_STORE)
    # Съобщението казва КАКВО да се зададе — иначе остава „не работи“.
    assert "APPLE_ISSUER_ID" in str(exc.value) and "APPLE_VENDOR_NUMBER" in str(exc.value)


def test_sync_na_nesvurzan_magazin_e_409(client, monkeypatch):
    """Телефонът/екранът получава причината, не измислени редове."""
    from app.modules.stores.connectors import factory

    h = _setup(client, "st-off@example.com")
    monkeypatch.setattr(factory.settings, "STORE_PROVIDER", "auto", raising=False)
    r = client.post(f"{ST}/GOOGLE_PLAY/sync?date_from=2026-06-01&date_to=2026-06-02", headers=h)
    assert r.status_code == 409, r.text
    assert "Google Play" in r.json()["detail"]
    assert "GOOGLE_PLAY_BUCKET" in r.json()["detail"]
    # и нищо не е записано
    assert client.get(f"{ST}/sales", headers=h).json() == []


def test_status_kazva_rezhima_na_vseki_magazin(client, monkeypatch, tmp_path):
    from app.modules.stores import router as stores_router

    klyuch = tmp_path / "AuthKey_TEST.p8"
    klyuch.write_text("-----BEGIN PRIVATE KEY-----\nproba\n-----END PRIVATE KEY-----\n")
    h = _setup(client, "st-status2@example.com")
    monkeypatch.setattr(stores_router.settings, "STORE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(stores_router.settings, "APPLE_ISSUER_ID", "iss", raising=False)
    monkeypatch.setattr(stores_router.settings, "APPLE_KEY_ID", "kid", raising=False)
    monkeypatch.setattr(stores_router.settings, "APPLE_VENDOR_NUMBER", "87654321", raising=False)
    monkeypatch.setattr(
        stores_router.settings, "APPLE_PRIVATE_KEY_PATH", str(klyuch), raising=False
    )
    s = client.get(f"{ST}/status", headers=h).json()
    assert s["platforms"] == {"APP_STORE": "live", "GOOGLE_PLAY": "off"}


# ---- Реалният отчет не е един ред на ден, приложение и държава -------------

def test_sync_sabira_povtarqshtite_se_redove_a_ne_gi_izhvurlya(client, monkeypatch):
    """Apple дава няколко реда за един ден/приложение/държава/тип.

    Старият код смяташе втория за „дубликат“ и го изхвърляше — приходът му
    изчезваше. Тук два реда по 10,00 трябва да дадат 20,00.
    """
    from app.modules.stores.connectors import factory
    from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
    from app.modules.stores.models import StoreProductType

    def red(units: int, proceeds: str) -> StoreSaleData:
        return StoreSaleData(
            platform=StorePlatform.APP_STORE, report_date=dt.date(2026, 6, 1),
            app_name="Beagle Owner", app_identifier="mybeagle-ios-001", country="BG",
            units=units, proceeds=Decimal(proceeds), currency="EUR",
            product_type=StoreProductType.APP,
        )

    class DvaReda(StoreConnector):
        platform = StorePlatform.APP_STORE

        def fetch_sales(self, date_from, date_to):
            return [red(1, "10.00"), red(2, "10.00")]

    monkeypatch.setattr(factory, "get_connector", lambda p: DvaReda())
    from app.modules.stores import service as stores_service
    monkeypatch.setattr(stores_service, "get_connector", lambda p: DvaReda())

    h = _setup(client, "st-agg@example.com")
    r = client.post(f"{ST}/APP_STORE/sync?date_from=2026-06-01&date_to=2026-06-01", headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["fetched"] == 2
    assert res["imported"] == 1 and res["duplicates"] == 0
    sales = client.get(f"{ST}/sales", headers=h).json()
    assert len(sales) == 1
    assert sales[0]["units"] == 3
    assert Decimal(sales[0]["proceeds"]) == Decimal("20.00")


def test_povtorno_sinhronizirane_obnovyava_koregiran_otchet(client, monkeypatch):
    """Месечният отчет на Google расте всеки ден; Apple коригира ден назад.

    Старият код пропускаше вече съществуващия ред, тоест първото
    синхронизиране на месеца заковаваше числата му завинаги.
    """
    from app.modules.stores import service as stores_service
    from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
    from app.modules.stores.models import StoreProductType

    suma = {"v": "5.00", "units": 1}

    class Rastyasht(StoreConnector):
        platform = StorePlatform.GOOGLE_PLAY

        def fetch_sales(self, date_from, date_to):
            return [StoreSaleData(
                platform=StorePlatform.GOOGLE_PLAY, report_date=dt.date(2026, 6, 1),
                app_name="My Life Within", app_identifier="com.heppsu.mylifewithin",
                country="DE", units=suma["units"], proceeds=Decimal(suma["v"]),
                currency="EUR", product_type=StoreProductType.SUBSCRIPTION,
            )]

    monkeypatch.setattr(stores_service, "get_connector", lambda p: Rastyasht())
    h = _setup(client, "st-upd@example.com")
    q = "date_from=2026-06-01&date_to=2026-06-01"
    assert client.post(f"{ST}/GOOGLE_PLAY/sync?{q}", headers=h).json()["imported"] == 1

    suma["v"], suma["units"] = "12.50", 3
    r2 = client.post(f"{ST}/GOOGLE_PLAY/sync?{q}", headers=h).json()
    assert r2["updated"] == 1 and r2["imported"] == 0 and r2["duplicates"] == 0
    sales = client.get(f"{ST}/sales", headers=h).json()
    assert len(sales) == 1
    assert Decimal(sales[0]["proceeds"]) == Decimal("12.50") and sales[0]["units"] == 3

    # Трето пускане без промяна в отчета не брои обновяване.
    r3 = client.post(f"{ST}/GOOGLE_PLAY/sync?{q}", headers=h).json()
    assert r3["duplicates"] == 1 and r3["updated"] == 0


# ---- App Store: отчетът -----------------------------------------------------

def test_appstore_abonamentut_ne_e_vutreshna_pokupka():
    """IAY/IA9/IAC са абонаменти. Проверката за „IA“ стоеше първа и ги поглъщаше."""
    from app.modules.stores.connectors.appstore import _product_type
    from app.modules.stores.models import StoreProductType

    assert _product_type("IAY") == StoreProductType.SUBSCRIPTION
    assert _product_type("IA9") == StoreProductType.SUBSCRIPTION
    assert _product_type("IAC") == StoreProductType.SUBSCRIPTION
    assert _product_type("IA1") == StoreProductType.IN_APP
    assert _product_type("1") == StoreProductType.APP
    assert _product_type("1F") == StoreProductType.APP


def test_appstore_tegli_versiya_1_1_na_otcheta():
    """С „1_0“ Apple връща 400 и нула реда при напълно изправни ключове."""
    from app.modules.stores.connectors import appstore

    tekst = pathlib.Path(appstore.__file__.removesuffix("c")).read_text(encoding="utf-8")
    assert '"filter[version]": "1_1"' in tekst
    assert '"filter[version]": "1_0"' not in tekst


def test_appstore_prihodut_e_po_edinica_po_broyka():
    """`Developer Proceeds` е за ЕДНА бройка — умножава се по Units."""
    from app.modules.stores.connectors.appstore import AppStoreConnector

    tsv = (
        "Provider\tSKU\tTitle\tUnits\tDeveloper Proceeds\tCountry Code\t"
        "Currency of Proceeds\tProduct Type Identifier\n"
        "APPLE\tmybeagle-ios-001\tBeagle Owner\t3\t2.10\tBG\tEUR\tIAY\n"
    )
    rows = AppStoreConnector()._parse_tsv(tsv, dt.date(2026, 10, 1))
    assert len(rows) == 1
    assert rows[0].units == 3
    assert rows[0].proceeds == Decimal("6.30")
    assert rows[0].app_identifier == "mybeagle-ios-001"
    assert rows[0].product_type.value == "SUBSCRIPTION"


# ---- Google Play: отчетът в кофата -----------------------------------------

def test_googleplay_chete_utf16_otchet():
    """Отчетите на Play са UTF-16LE с BOM; UTF-8 ги правеше безсмислица."""
    from app.modules.stores.connectors.googleplay import decode_report

    red = "Transaction Date,Product Title\n2026-10-01,Beagle Owner\n"
    assert decode_report(red.encode("utf-16")) .startswith("Transaction Date")
    assert decode_report(red.encode("utf-8")).startswith("Transaction Date")


def test_googleplay_prilozhenieto_e_package_id():
    """Колоната е `Package ID`. „Product id“ не съществува в отчетите на Play.

    Прочетено от живите отчети в кофата на 26.10.2026: приходът на Beagle Owner
    се записваше срещу „plus_monthly“, защото кодът търсеше несъществуваща
    колона и падаше на Sku Id.
    """
    from app.modules.stores.connectors.googleplay import GooglePlayConnector

    csv_text = (
        "Transaction Date,Transaction Type,Product Title,Package ID,Product Type,"
        "Sku Id,Buyer Country,Merchant Currency,Amount (Merchant Currency)\n"
        '"Sep 6, 2026",Charge,My Beagle Plus (My Beagle),com.heppsu.myBeagle,'
        "Subscription,plus_monthly,BG,EUR,0.83\n"
    )
    r = GooglePlayConnector().parse_csv(csv_text)[0]
    assert r.app_identifier == "com.heppsu.myBeagle"
    assert r.app_name == "My Beagle Plus (My Beagle)"
    assert r.report_date == dt.date(2026, 9, 6)   # „Sep 6, 2026“, не ISO


def test_googleplay_salesreport_e_zip_s_vrushtane():
    """Текущият месец има САМО отчет за продажбите — и той е ZIP.

    `earnings_YYYYMM` излиза след края на месеца. Старият код теглеше
    `sales/salesreport_YYYYMM.csv`, а файлът е `.zip`: 404 и нула реда за
    текущия месец. Връщането е отрицателна бройка, не +1.
    """
    import io
    import zipfile

    from app.modules.stores.connectors.googleplay import GooglePlayConnector

    csv_text = (
        "Order Charged Date,Financial Status,Product Title,Package ID,Product Type,"
        "SKU ID,Currency of Sale,Charged Amount,Country of Buyer\n"
        "2026-10-14,Charged,Beagle Owner Plus,com.heppsu.myBeagle,Subscription,"
        "plus_monthly,CHF,0.80,CH\n"
        "2026-10-20,Refund,Beagle Owner Plus,com.heppsu.myBeagle,Subscription,"
        "plus_monthly,CHF,-0.80,CH\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("salesreport_202610.csv", csv_text.encode("utf-16"))

    rows = GooglePlayConnector().parse_archive(buf.getvalue())
    assert [r.units for r in rows] == [1, -1]
    assert [r.country for r in rows] == ["CH", "CH"]
    assert rows[0].currency == "CHF"
    assert sum(r.proceeds for r in rows) == Decimal("0.00")


def test_googleplay_tegli_zip_a_na_prodazhbite(monkeypatch):
    """Изброяване по префикс, не заковано `.csv` име."""
    from app.modules.stores.connectors import googleplay

    poiskani: list[str] = []

    k = googleplay.GooglePlayConnector()
    monkeypatch.setattr(k, "_access_token", lambda: "t")
    monkeypatch.setattr(
        k, "_list",
        lambda client, bucket, prefix: (poiskani.append(prefix) or [])
        if "earnings" in prefix else (poiskani.append(prefix) or ["sales/salesreport_202610.zip"]),
    )
    monkeypatch.setattr(k, "_download", lambda client, bucket, obj: None)
    monkeypatch.setattr(googleplay.settings, "GOOGLE_PLAY_BUCKET", "kofa", raising=False)
    k.fetch_sales(dt.date(2026, 10, 1), dt.date(2026, 10, 25))
    assert "sales/salesreport_202610" in poiskani
    assert not any(p.endswith(".csv") for p in poiskani)


def test_apple_bez_valuta_ne_izprazva_valutata_na_reda(client, monkeypatch):
    """Безплатното изтегляне в отчета на Apple идва без „Currency of Proceeds“."""
    from app.modules.stores import service as stores_service
    from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
    from app.modules.stores.models import StoreProductType

    def red(valuta: str, proceeds: str) -> StoreSaleData:
        return StoreSaleData(
            platform=StorePlatform.APP_STORE, report_date=dt.date(2026, 10, 1),
            app_name="My Life Within", app_identifier="mylifewithin-ios-001",
            country="BG", units=1, proceeds=Decimal(proceeds), currency=valuta,
            product_type=StoreProductType.APP,
        )

    class BezValuta(StoreConnector):
        platform = StorePlatform.APP_STORE

        def fetch_sales(self, date_from, date_to):
            return [red("", "0.00"), red("EUR", "2.10")]

    monkeypatch.setattr(stores_service, "get_connector", lambda p: BezValuta())
    h = _setup(client, "st-val@example.com")
    client.post(f"{ST}/APP_STORE/sync?date_from=2026-10-01&date_to=2026-10-01", headers=h)
    sales = client.get(f"{ST}/sales", headers=h).json()
    assert len(sales) == 1 and sales[0]["currency"] == "EUR"


def test_googleplay_earnings_zip_dava_nettoto():
    """`earnings_YYYYMM_*.zip` е архив с CSV, не един CSV.

    Таксата на Google и данъкът са отделни отрицателни редове в същия отчет —
    затова нетното излиза само ако се съберат всички.
    """
    import io
    import zipfile

    from app.modules.stores.connectors.googleplay import GooglePlayConnector

    csv_text = (
        "Description,Transaction Date,Transaction Type,Product Title,Product id,"
        "Product Type,Buyer Country,Merchant Currency,Amount (Merchant Currency)\n"
        "Order,2026-10-01,Charge,My Life Within,com.heppsu.mylifewithin,Subscription,DE,EUR,9.99\n"
        "Fee,2026-10-01,Google fee,My Life Within,com.heppsu.mylifewithin,Subscription,DE,EUR,-1.50\n"
    )
        # UTF-16, както излиза от Play
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("earnings_202610.csv", csv_text.encode("utf-16"))

    rows = GooglePlayConnector().parse_archive(buf.getvalue())
    assert len(rows) == 2
    # Покупката носи бройка, таксата — не.
    assert [r.units for r in rows] == [1, 0]
    assert sum(r.proceeds for r in rows) == Decimal("8.49")
    assert rows[0].product_type.value == "SUBSCRIPTION"
    assert rows[0].app_identifier == "com.heppsu.mylifewithin"
    assert rows[0].country == "DE"


def test_googleplay_ne_iska_google_cloud_storage():
    """Пакетът го няма в образа — конекторът говори с GCS през httpx."""
    from app.modules.stores.connectors import googleplay

    tekst = pathlib.Path(googleplay.__file__.removesuffix("c")).read_text(encoding="utf-8")
    assert "google.cloud" not in tekst
    assert "storage.googleapis.com" in tekst


def test_googleplay_mesecite_prez_granica_na_godina():
    from app.modules.stores.connectors.googleplay import GooglePlayConnector

    m = GooglePlayConnector().months(dt.date(2025, 11, 20), dt.date(2026, 2, 3))
    assert m == ["202511", "202512", "202601", "202602"]


def test_es256_i_rs256_se_podpisvat():
    """Без `cryptography` PyJWT вдига NotImplementedError и нищо не се свързва.

    Точно това беше състоянието в production до 26.10.2026: `pyjwt` без
    `[crypto]`, тоест реалните конектори не можеха да работят дори с ключове.
    """
    # Зависимостта, с която се строи образът — иначе локално инсталираното
    # `cryptography` крие липсата в production.
    trebva = pathlib.Path(__file__).resolve().parents[1] / "requirements.txt"
    tekst = trebva.read_text(encoding="utf-8")
    assert "pyjwt[crypto]==" in tekst, "`pyjwt` без [crypto] не подписва ES256/RS256"
    assert "\nhttpx==" in tekst, "httpx е нужен на конекторите, не само на тестовете"

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    es = ec.generate_private_key(ec.SECP256R1())
    assert jwt.encode({"a": 1}, es, algorithm="ES256")
    rs = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert jwt.encode({"a": 1}, rs, algorithm="RS256")


def test_analitikata_ne_etiketira_chuzhda_valuta_kato_bazovata(client, monkeypatch):
    """0,80 CHF от Швейцария не са „0,80 EUR“.

    `currency` идваше от `company.base_currency`, тоест екранът етикетираше
    всеки приход с валутата на дружеството. Реалните отчети са многовалутни и
    системата няма източник на курсове — затова сборът през валути няма валута,
    а истинският сбор е `by_currency`.
    """
    from app.modules.stores import service as stores_service
    from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
    from app.modules.stores.models import StoreProductType

    def red(valuta: str, suma: str, darzhava: str, den: int) -> StoreSaleData:
        return StoreSaleData(
            platform=StorePlatform.GOOGLE_PLAY, report_date=dt.date(2026, 10, den),
            app_name="Beagle Owner Plus", app_identifier="com.heppsu.myBeagle",
            country=darzhava, units=1, proceeds=Decimal(suma), currency=valuta,
            product_type=StoreProductType.SUBSCRIPTION,
        )

    class Mnogovalutno(StoreConnector):
        platform = StorePlatform.GOOGLE_PLAY

        def fetch_sales(self, date_from, date_to):
            return [red("CHF", "0.80", "CH", 14), red("EUR", "0.83", "BG", 6)]

    monkeypatch.setattr(stores_service, "get_connector", lambda p: Mnogovalutno())
    h = _setup(client, "st-val2@example.com")
    client.post(f"{ST}/GOOGLE_PLAY/sync?date_from=2026-10-01&date_to=2026-10-31", headers=h)
    a = client.get(f"{ST}/analytics", headers=h).json()

    # Сборът през две валути няма валута — не е „EUR“, защото дружеството е в EUR.
    assert a["currency"] == ""
    po_valuti = {c["key"]: Decimal(c["proceeds"]) for c in a["by_currency"]}
    assert po_valuti == {"CHF": Decimal("0.80"), "EUR": Decimal("0.83")}
    # Редът по държава носи своята валута, защото е една.
    po_darzhavi = {c["key"]: c["currency"] for c in a["by_country"]}
    assert po_darzhavi == {"CH": "CHF", "BG": "EUR"}
    # Приложението е едно, но в две валути → редът няма валута.
    assert [c["currency"] for c in a["by_app"]] == [""]


def test_analitikata_s_edna_valuta_ya_nazovava(client, monkeypatch):
    from app.modules.stores import service as stores_service
    from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
    from app.modules.stores.models import StoreProductType

    class Ednovalutno(StoreConnector):
        platform = StorePlatform.APP_STORE

        def fetch_sales(self, date_from, date_to):
            return [StoreSaleData(
                platform=StorePlatform.APP_STORE, report_date=dt.date(2026, 10, 2),
                app_name="My Life Within", app_identifier="mylifewithin-ios-001",
                country="BG", units=2, proceeds=Decimal("4.20"), currency="EUR",
                product_type=StoreProductType.APP,
            )]

    monkeypatch.setattr(stores_service, "get_connector", lambda p: Ednovalutno())
    h = _setup(client, "st-val3@example.com")
    client.post(f"{ST}/APP_STORE/sync?date_from=2026-10-01&date_to=2026-10-31", headers=h)
    a = client.get(f"{ST}/analytics", headers=h).json()
    assert a["currency"] == "EUR"
    assert [c["key"] for c in a["by_currency"]] == ["EUR"]
