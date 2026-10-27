"""Ключът на магазина е ФАЙЛ, не настройка — и липсващият файл не е 500.

27.10.2026, 22:10, production: пет опита за синхронизиране на App Store, пет
пъти 500 Internal Server Error. В лога:

    File "app/modules/stores/connectors/appstore.py", line 40, in _jwt
    FileNotFoundError: '/app/secrets/AuthKey_5FHYZ9NAMB.p8'

Трите настройки на Apple бяха зададени, затова `apple_configured` беше True,
режимът — „live“, а екранът показваше магазина за свързан. Ключът обаче е
файл на този път, и файлът не се четеше. „Конфигуриран“ се проверяваше по
зададени настройки, не по наличния ключ.

Тези тестове държат проверката вързана за самия ключ: зададен път без четим
файл не е свързан магазин, екранът го казва, а синхронизирането връща 409 с
причината — не 500 с traceback.
"""
import pathlib

import pytest

from app.core.config import Settings
from app.modules.stores.connectors.factory import StoreNotConnected, get_connector
from app.modules.stores.models import StorePlatform
from tests.conftest import register_and_login

ST = "/api/v1/stores"
PERIOD = "date_from=2026-06-01&date_to=2026-06-07"


def _nastroiki(**kw) -> Settings:
    bazovi = {"SECRET_KEY": "x" * 40, "ENVIRONMENT": "test", "STORE_PROVIDER": "auto"}
    return Settings(**{**bazovi, **kw})


def _apple(path: str, **kw) -> Settings:
    return _nastroiki(
        APPLE_ISSUER_ID="69a6de7f-0000-47e3-e053-5b8c7c11a4d1",
        APPLE_KEY_ID="5FHYZ9NAMB",
        APPLE_PRIVATE_KEY_PATH=path,
        APPLE_VENDOR_NUMBER="87654321",
        **kw,
    )


def _google(path: str, **kw) -> Settings:
    return _nastroiki(
        GOOGLE_PLAY_BUCKET="pubsite_prod_rev_01234567890123456789",
        GOOGLE_APPLICATION_CREDENTIALS=path,
        **kw,
    )


def _klyuch(tmp_path, name: str = "AuthKey_5FHYZ9NAMB.p8") -> str:
    """Четим файл на мястото на ключа (съдържанието няма значение тук)."""
    fayl = tmp_path / name
    fayl.write_text("-----BEGIN PRIVATE KEY-----\nproba\n-----END PRIVATE KEY-----\n")
    return str(fayl)


# ---------------------------------------------------------------- настройките


def test_zadaden_pat_bez_fayl_ne_e_svarzan_apple(tmp_path):
    """Трите настройки на Apple са зададени, но ключът го няма на диска."""
    s = _apple(str(tmp_path / "nyama-go.p8"))
    assert s.apple_configured is False
    assert s.store_provider_for("APP_STORE") == "off"


def test_zadaden_pat_bez_fayl_ne_e_svarzan_google(tmp_path):
    s = _google(str(tmp_path / "nyama-go.json"))
    assert s.google_play_configured is False
    assert s.store_provider_for("GOOGLE_PLAY") == "off"


def test_chetim_fayl_e_svarzan_magazin(tmp_path):
    """Обратната посока: с ключа на място магазинът е свързан."""
    assert _apple(_klyuch(tmp_path)).apple_configured is True
    assert _apple(_klyuch(tmp_path)).store_provider_for("APP_STORE") == "live"
    g = _google(_klyuch(tmp_path, "play-service-account.json"))
    assert g.google_play_configured is True
    assert g.store_provider_for("GOOGLE_PLAY") == "live"


def test_direktoriya_na_mestoto_na_klyucha_ne_e_klyuch(tmp_path):
    """Път, който сочи директория, не е четим ключ — отваряното би било IsADirectoryError."""
    (tmp_path / "secrets").mkdir()
    assert _apple(str(tmp_path / "secrets")).apple_configured is False


def test_apple_bez_vendor_number_ne_e_svarzan(tmp_path):
    """Без номер на доставчика Apple връща 400 за всеки отчет — това не е „свързан“."""
    s = _nastroiki(
        APPLE_ISSUER_ID="69a6de7f-0000-47e3-e053-5b8c7c11a4d1",
        APPLE_KEY_ID="5FHYZ9NAMB",
        APPLE_PRIVATE_KEY_PATH=_klyuch(tmp_path),
        APPLE_VENDOR_NUMBER="",
    )
    assert s.apple_configured is False
    assert s.store_provider_for("APP_STORE") == "off"


# ---------------------------------------------------------------- конекторът


def _bez_klyuch(monkeypatch, tmp_path):
    """Среда с пълни настройки за Apple, но без файла на ключа."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(settings, "APPLE_ISSUER_ID", "69a6de7f-0000-47e3", raising=False)
    monkeypatch.setattr(settings, "APPLE_KEY_ID", "5FHYZ9NAMB", raising=False)
    monkeypatch.setattr(
        settings, "APPLE_PRIVATE_KEY_PATH", str(tmp_path / "nyama-go.p8"), raising=False
    )
    monkeypatch.setattr(settings, "APPLE_VENDOR_NUMBER", "87654321", raising=False)


def test_konektor_bez_fayl_vdiga_nazovana_greshka(monkeypatch, tmp_path):
    """`get_connector` отказва, вместо да върне конектор, който ще се счупи вътре."""
    _bez_klyuch(monkeypatch, tmp_path)
    with pytest.raises(StoreNotConnected):
        get_connector(StorePlatform.APP_STORE)


def test_greshkata_kazva_che_lipsva_fayl_a_ne_nastroyka(monkeypatch, tmp_path):
    """Съобщението насочва към ключа, иначе Ив търси зададена настройка."""
    _bez_klyuch(monkeypatch, tmp_path)
    with pytest.raises(StoreNotConnected) as izkl:
        get_connector(StorePlatform.APP_STORE)
    tekst = str(izkl.value)
    assert "файл" in tekst
    assert "nyama-go.p8" in tekst


# ---------------------------------------------------------------- през API


def _setup(client, email: str):
    token = register_and_login(client, email)
    auth = {"Authorization": f"Bearer {token}"}
    cid = client.post("/api/v1/companies", headers=auth, json={"name": "Хепсу ООД"}).json()["id"]
    return {**auth, "X-Company-Id": cid}


def test_sinhroniziraneto_bez_fayl_e_409_a_ne_500(client, monkeypatch, tmp_path):
    """Точният случай от production: пет 500-ки стават един четим 409."""
    h = _setup(client, "st-bez-klyuch@example.com")
    _bez_klyuch(monkeypatch, tmp_path)
    r = client.post(f"{ST}/APP_STORE/sync?{PERIOD}", headers=h)
    assert r.status_code == 409, r.text
    assert "App Store" in r.json()["detail"]
    assert "файл" in r.json()["detail"]


def test_ekranat_ne_kazva_svarzan_kogato_klyuchat_lipsva(client, monkeypatch, tmp_path):
    h = _setup(client, "st-status-bez-klyuch@example.com")
    _bez_klyuch(monkeypatch, tmp_path)
    s = client.get(f"{ST}/status", headers=h).json()
    assert s["apple_configured"] is False
    assert s["platforms"]["APP_STORE"] == "off"


def test_izcheznal_klyuch_sled_proverkata_e_409_a_ne_500(client, monkeypatch, tmp_path):
    """Ключът изчезва между проверката и четенето (деплой, размонтиран обем).

    Проверката вече е минала и конекторът е реален — грешката идва от самото
    четене на файла. И тя трябва да стигне до екрана като причина, не като 500.
    """
    from app.core.config import settings

    h = _setup(client, "st-izchezna@example.com")
    pat = _klyuch(tmp_path)
    monkeypatch.setattr(settings, "STORE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(settings, "APPLE_ISSUER_ID", "69a6de7f-0000-47e3", raising=False)
    monkeypatch.setattr(settings, "APPLE_KEY_ID", "5FHYZ9NAMB", raising=False)
    monkeypatch.setattr(settings, "APPLE_PRIVATE_KEY_PATH", pat, raising=False)
    monkeypatch.setattr(settings, "APPLE_VENDOR_NUMBER", "87654321", raising=False)
    assert settings.store_provider_for("APP_STORE") == "live"

    pathlib.Path(pat).unlink()  # обемът със secrets пада точно сега
    r = client.post(f"{ST}/APP_STORE/sync?{PERIOD}", headers=h)
    assert r.status_code == 409, r.text
    assert "файл" in r.json()["detail"]


def test_statusat_nosi_prichinata_za_vseki_nesvarzan_magazin(client, monkeypatch, tmp_path):
    """Екранът казва ЗАЩО, без да се натиска „Синхронизирай“ и да се чака грешка."""
    h = _setup(client, "st-prichina@example.com")
    _bez_klyuch(monkeypatch, tmp_path)
    s = client.get(f"{ST}/status", headers=h).json()
    assert "файл" in s["reasons"]["APP_STORE"]
    assert "nyama-go.p8" in s["reasons"]["APP_STORE"]
    # Google Play е без никакви настройки → причината сочи тях, не файл.
    assert "GOOGLE_PLAY_BUCKET" in s["reasons"]["GOOGLE_PLAY"]


def test_svarzan_magazin_nyama_prichina_v_statusa(client, monkeypatch, tmp_path):
    from app.core.config import settings

    h = _setup(client, "st-bez-prichina@example.com")
    monkeypatch.setattr(settings, "STORE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(settings, "APPLE_ISSUER_ID", "iss", raising=False)
    monkeypatch.setattr(settings, "APPLE_KEY_ID", "kid", raising=False)
    monkeypatch.setattr(settings, "APPLE_PRIVATE_KEY_PATH", _klyuch(tmp_path), raising=False)
    monkeypatch.setattr(settings, "APPLE_VENDOR_NUMBER", "87654321", raising=False)
    s = client.get(f"{ST}/status", headers=h).json()
    assert "APP_STORE" not in s["reasons"]


# ------------------------------------- магазинът отговаря, но с грешка


def test_greshka_ot_magazina_e_502_s_otgovora_a_ne_500(client, monkeypatch, tmp_path):
    """Свързан магазин, който отговаря 401/400, също не е вътрешна грешка.

    Изтекъл ключ, сгрешен vendor number и кофа без права минават проверката за
    конфигурираност и се чупят в мрежата. С голо `raise_for_status()` на екрана
    остава „Internal Server Error“, а причината — само в traceback на сървъра.
    """
    import httpx

    h = _setup(client, "st-401@example.com")
    _bez_klyuch(monkeypatch, tmp_path)  # пълни настройки
    from app.core.config import settings

    monkeypatch.setattr(settings, "APPLE_PRIVATE_KEY_PATH", _klyuch(tmp_path), raising=False)

    def _vdiga(self, date_from, date_to):
        otgovor = httpx.Response(
            401,
            json={"errors": [{"detail": "Authentication credentials are missing or invalid"}]},
            request=httpx.Request("GET", "https://api.appstoreconnect.apple.com/v1/salesReports"),
        )
        raise httpx.HTTPStatusError("401", request=otgovor.request, response=otgovor)

    from app.modules.stores.connectors.appstore import AppStoreConnector

    monkeypatch.setattr(AppStoreConnector, "fetch_sales", _vdiga)

    r = client.post(f"{ST}/APP_STORE/sync?{PERIOD}", headers=h)
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert "401" in detail
    assert "credentials" in detail       # причината от магазина стига до екрана
    assert client.get(f"{ST}/sales", headers=h).json() == []   # и нищо не е записано


def test_prekusnata_mrezha_kum_magazina_e_502(client, monkeypatch, tmp_path):
    import httpx

    h = _setup(client, "st-mrezha@example.com")
    _bez_klyuch(monkeypatch, tmp_path)
    from app.core.config import settings

    monkeypatch.setattr(settings, "APPLE_PRIVATE_KEY_PATH", _klyuch(tmp_path), raising=False)

    def _vdiga(self, date_from, date_to):
        raise httpx.ConnectTimeout("време за свързване изтече")

    from app.modules.stores.connectors.appstore import AppStoreConnector

    monkeypatch.setattr(AppStoreConnector, "fetch_sales", _vdiga)

    r = client.post(f"{ST}/APP_STORE/sync?{PERIOD}", headers=h)
    assert r.status_code == 502, r.text
    assert "APP_STORE" in r.json()["detail"]
