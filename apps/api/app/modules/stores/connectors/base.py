"""Контракт за конекторите към магазините (App Store / Google Play).

Всеки конектор капсулира API-то на съответния магазин и връща нормализирани редове
продажби (`StoreSaleData`). Ядрото на модула работи само през този контракт, така че
магазините са взаимозаменяеми плъгини (реален или stub конектор).
"""
from __future__ import annotations

import datetime as dt
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.modules.stores.models import StorePlatform, StoreProductType


@dataclass
class StoreSaleData:
    """Нормализиран ред продажби от магазин (независим от източника)."""

    platform: StorePlatform
    report_date: dt.date
    app_name: str
    app_identifier: str
    country: str
    units: int
    proceeds: Decimal
    currency: str
    product_type: StoreProductType = StoreProductType.APP

    def source_ref(self) -> str:
        """Стабилен естествен ключ за дедупликация."""
        raw = f"{self.platform.value}|{self.report_date.isoformat()}|{self.app_identifier}|{self.country}|{self.product_type.value}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


class StoreConnector(ABC):
    platform: StorePlatform

    @abstractmethod
    def fetch_sales(self, date_from: dt.date, date_to: dt.date) -> list[StoreSaleData]:
        """Изтегля и нормализира продажбите за периода [date_from, date_to]."""
        raise NotImplementedError
