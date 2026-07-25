"""Детерминиран stub конектор — генерира правдоподобни данни за продажби без мрежа.

Ползва се за dev/демо/тестове, докато няма конфигурирани реални credentials (по същия
модел като StubLLMClient в AI модула). Данните са изцяло функция на входа (без random),
за да са възпроизводими.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
from app.modules.stores.models import StorePlatform, StoreProductType

# Примерно портфолио от приложения (различни за двата магазина).
_APPS = {
    StorePlatform.APP_STORE: [
        ("Heppsu Invoice", "com.heppsu.invoice", StoreProductType.APP, Decimal("3.99")),
        ("Heppsu Pro", "com.heppsu.pro", StoreProductType.SUBSCRIPTION, Decimal("9.99")),
        ("Heppsu Scan", "com.heppsu.scan", StoreProductType.IN_APP, Decimal("1.99")),
    ],
    StorePlatform.GOOGLE_PLAY: [
        ("Heppsu Invoice", "com.heppsu.invoice", StoreProductType.APP, Decimal("3.49")),
        ("Heppsu Pro", "com.heppsu.pro", StoreProductType.SUBSCRIPTION, Decimal("8.99")),
    ],
}
_COUNTRIES = ["BG", "DE", "US", "GB", "FR"]
_CURRENCY = {"BG": "EUR", "DE": "EUR", "FR": "EUR", "US": "USD", "GB": "GBP"}


class StubStoreConnector(StoreConnector):
    def __init__(self, platform: StorePlatform):
        self.platform = platform

    def fetch_sales(self, date_from: dt.date, date_to: dt.date) -> list[StoreSaleData]:
        rows: list[StoreSaleData] = []
        apps = _APPS[self.platform]
        day = date_from
        idx = 0
        while day <= date_to:
            for a_i, (name, ident, ptype, price) in enumerate(apps):
                for c_i, country in enumerate(_COUNTRIES):
                    # Детерминиран „обем" от индексите (без random).
                    units = ((day.toordinal() + a_i * 3 + c_i * 2) % 7) + a_i + 1
                    if units <= 0:
                        continue
                    proceeds = (price * Decimal("0.85") * units).quantize(Decimal("0.01"))  # ~15% комисиона
                    rows.append(
                        StoreSaleData(
                            platform=self.platform,
                            report_date=day,
                            app_name=name,
                            app_identifier=ident,
                            country=country,
                            units=units,
                            proceeds=proceeds,
                            currency=_CURRENCY[country],
                            product_type=ptype,
                        )
                    )
                    idx += 1
            day += dt.timedelta(days=1)
        return rows
