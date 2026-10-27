"""Избор на конектор за един магазин: реален, подставен или никакъв.

Режимът е НА МАГАЗИН (`settings.store_provider_for`), защото ключовете са на
магазин. По-рано беше един общ режим и „live“ се включваше, щом е конфигуриран
кой да е от двата магазина — синхронизирането на Google Play тръгваше към
реалния конектор само защото Apple има ключ, и падаше вътре в него с ImportError.

Липсващи ключове дават `StoreNotConnected`, не подставени данни: на 26.10.2026
production носеше 1305 реда измислени продажби на приложения, които не
съществуват, и те се четяха като счетоводни данни.

„Няма ключ“ значи и „ключът не се чете“. Ключът е файл на пътя от настройката
и зададеният път не е наличен ключ: на 27.10.2026 настройките на Apple бяха
налице, обемът `secrets` не беше монтиран в контейнера и всяко синхронизиране
връщаше 500 с `FileNotFoundError`, докато екранът показваше „свързан“.
"""
from __future__ import annotations

from app.core.config import chetim_fayl, settings
from app.modules.stores.connectors.base import StoreConnector
from app.modules.stores.connectors.stub import StubStoreConnector
from app.modules.stores.models import StorePlatform

NAZVANIE = {
    StorePlatform.APP_STORE: "App Store",
    StorePlatform.GOOGLE_PLAY: "Google Play",
}

# Какво трябва да се зададе в средата, за да се включи магазинът. Ключът е
# отделно: той е ФАЙЛ на пътя от настройката, а не самата настройка.
NUZHNI_NASTROYKI = {
    StorePlatform.APP_STORE: {
        "APPLE_ISSUER_ID": "идентификатор на издателя в App Store Connect",
        "APPLE_KEY_ID": "идентификатор на ключа",
        "APPLE_VENDOR_NUMBER": "номер на доставчика (за Sales Reports)",
    },
    StorePlatform.GOOGLE_PLAY: {
        "GOOGLE_PLAY_BUCKET": "кофата pubsite_prod_rev_… с отчетите",
    },
}
# Настройката, която носи ПЪТЯ до ключа, и какво е той.
NUZHEN_KLYUCH = {
    StorePlatform.APP_STORE: ("APPLE_PRIVATE_KEY_PATH", "частният ключ .p8"),
    StorePlatform.GOOGLE_PLAY: (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "service account JSON с достъп до кофата",
    ),
}


def prichina_za_nesvarzan(platform: StorePlatform) -> str:
    """Защо точно този магазин не е свързан: липсваща настройка или нечетим ключ.

    Статичният списък „задай в средата: …“ беше недостатъчен. На 27.10.2026
    всички настройки на Apple бяха зададени и липсваше САМО файлът на ключа, а
    съобщението пращаше да се проверяват настройки — тоест вярно изброяване,
    което сочи в грешната посока.
    """
    nastroyki = {
        ime: getattr(settings, ime, "") for ime in NUZHNI_NASTROYKI[platform]
    }
    ime_na_klyucha, kakvo = NUZHEN_KLYUCH[platform]
    pat = getattr(settings, ime_na_klyucha, "")

    lipsvashti = [
        f"{ime} ({NUZHNI_NASTROYKI[platform][ime]})"
        for ime, stoynost in nastroyki.items()
        if not stoynost
    ]
    if not pat:
        lipsvashti.append(f"{ime_na_klyucha} (пътят до {kakvo})")

    prichini = []
    if lipsvashti:
        prichini.append("задай в средата: " + ", ".join(lipsvashti))
    if pat and not chetim_fayl(pat):
        prichini.append(
            f"файлът с ключа ({kakvo}) не се чете на пътя от {ime_na_klyucha}: {pat}"
        )
    return "; ".join(prichini) or "няма ключове"


class StoreNotConnected(RuntimeError):
    """Магазинът не е свързан — няма откъде да дойдат реални данни."""

    def __init__(self, platform: StorePlatform):
        self.platform = platform
        super().__init__(
            f"{NAZVANIE[platform]} не е свързан — {prichina_za_nesvarzan(platform)}."
        )


def get_connector(platform: StorePlatform) -> StoreConnector:
    rezhim = settings.store_provider_for(platform.value)
    if rezhim == "live":
        if platform == StorePlatform.APP_STORE:
            from app.modules.stores.connectors.appstore import AppStoreConnector

            return AppStoreConnector()
        from app.modules.stores.connectors.googleplay import GooglePlayConnector

        return GooglePlayConnector()
    if rezhim == "stub":
        return StubStoreConnector(platform)
    raise StoreNotConnected(platform)
