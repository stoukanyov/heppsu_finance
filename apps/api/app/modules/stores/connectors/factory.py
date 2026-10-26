"""Избор на конектор за един магазин: реален, подставен или никакъв.

Режимът е НА МАГАЗИН (`settings.store_provider_for`), защото ключовете са на
магазин. По-рано беше един общ режим и „live“ се включваше, щом е конфигуриран
кой да е от двата магазина — синхронизирането на Google Play тръгваше към
реалния конектор само защото Apple има ключ, и падаше вътре в него с ImportError.

Липсващи ключове дават `StoreNotConnected`, не подставени данни: на 26.10.2026
production носеше 1305 реда измислени продажби на приложения, които не
съществуват, и те се четяха като счетоводни данни.
"""
from __future__ import annotations

from app.core.config import settings
from app.modules.stores.connectors.base import StoreConnector
from app.modules.stores.connectors.stub import StubStoreConnector
from app.modules.stores.models import StorePlatform

NAZVANIE = {
    StorePlatform.APP_STORE: "App Store",
    StorePlatform.GOOGLE_PLAY: "Google Play",
}

# Какво трябва да се зададе в средата, за да се включи магазинът.
NUZHNI_NASTROYKI = {
    StorePlatform.APP_STORE: (
        "APPLE_ISSUER_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY_PATH (файлът .p8) "
        "и APPLE_VENDOR_NUMBER"
    ),
    StorePlatform.GOOGLE_PLAY: (
        "GOOGLE_PLAY_BUCKET (кофата pubsite_prod_rev_… с отчетите) и "
        "GOOGLE_APPLICATION_CREDENTIALS (service account JSON с достъп до нея)"
    ),
}


class StoreNotConnected(RuntimeError):
    """Магазинът не е свързан — няма откъде да дойдат реални данни."""

    def __init__(self, platform: StorePlatform):
        self.platform = platform
        super().__init__(
            f"{NAZVANIE[platform]} не е свързан. За реални данни задай в средата: "
            f"{NUZHNI_NASTROYKI[platform]}."
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
