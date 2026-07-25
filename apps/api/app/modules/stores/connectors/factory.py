"""Избор на конектор: реален (при налични credentials) или stub."""
from __future__ import annotations

from app.core.config import settings
from app.modules.stores.connectors.base import StoreConnector
from app.modules.stores.connectors.stub import StubStoreConnector
from app.modules.stores.models import StorePlatform


def get_connector(platform: StorePlatform) -> StoreConnector:
    if settings.resolved_store_provider == "live":
        if platform == StorePlatform.APP_STORE:
            from app.modules.stores.connectors.appstore import AppStoreConnector

            return AppStoreConnector()
        from app.modules.stores.connectors.googleplay import GooglePlayConnector

        return GooglePlayConnector()
    return StubStoreConnector(platform)
