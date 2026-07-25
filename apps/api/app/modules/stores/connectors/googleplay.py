"""Google Play — конектор за финансовите (earnings/sales) отчети.

Google Play експортира месечни CSV отчети в Google Cloud Storage bucket
(GOOGLE_PLAY_BUCKET) с достъп чрез service account (GOOGLE_APPLICATION_CREDENTIALS).
Конекторът изтегля релевантните месеци и нормализира редовете. Изтеглянето от GCS
изисква пакета `google-cloud-storage`; логиката за парсване е самостоятелна и покрита с
тестове. По подразбиране се ползва stub конекторът, докато няма credentials.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
from app.modules.stores.models import StorePlatform, StoreProductType


def _product_type(code: str) -> StoreProductType:
    code = (code or "").lower()
    if "subscription" in code:
        return StoreProductType.SUBSCRIPTION
    if "in-app" in code or "inapp" in code:
        return StoreProductType.IN_APP
    return StoreProductType.APP


class GooglePlayConnector(StoreConnector):
    platform = StorePlatform.GOOGLE_PLAY

    def parse_csv(self, text: str) -> list[StoreSaleData]:
        """Парсва Google Play earnings/sales CSV в нормализирани редове."""
        reader = csv.DictReader(io.StringIO(text))
        rows: list[StoreSaleData] = []
        for r in reader:
            date_str = (r.get("Transaction Date") or r.get("Order Charged Date") or "").strip()
            report_date = _parse_date(date_str)
            if report_date is None:
                continue
            try:
                amount = Decimal((r.get("Amount (Merchant Currency)") or "0").replace(",", "") or "0")
            except InvalidOperation:
                continue
            units = 1
            try:
                units = int(r.get("Quantity") or 1)
            except ValueError:
                units = 1
            rows.append(
                StoreSaleData(
                    platform=self.platform,
                    report_date=report_date,
                    app_name=(r.get("Product Title") or r.get("Product id") or "").strip(),
                    app_identifier=(r.get("Product id") or r.get("Sku Id") or "").strip(),
                    country=(r.get("Buyer Country") or "")[:2],
                    units=units,
                    proceeds=amount.quantize(Decimal("0.01")),
                    currency=(r.get("Currency of Sale") or r.get("Merchant Currency") or "EUR")[:3],
                    product_type=_product_type(r.get("Product Type") or ""),
                )
            )
        return rows

    def _months(self, date_from: dt.date, date_to: dt.date) -> list[str]:
        months, cur = [], dt.date(date_from.year, date_from.month, 1)
        while cur <= date_to:
            months.append(cur.strftime("%Y%m"))
            cur = dt.date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
        return months

    def fetch_sales(self, date_from: dt.date, date_to: dt.date) -> list[StoreSaleData]:
        from google.cloud import storage  # изисква google-cloud-storage

        client = storage.Client.from_service_account_json(settings.GOOGLE_APPLICATION_CREDENTIALS)
        bucket = client.bucket(settings.GOOGLE_PLAY_BUCKET)
        out: list[StoreSaleData] = []
        for ym in self._months(date_from, date_to):
            blob = bucket.blob(f"sales/salesreport_{ym}.csv")
            if not blob.exists():
                continue
            text = blob.download_as_text()
            out.extend(r for r in self.parse_csv(text) if date_from <= r.report_date <= date_to)
        return out


def _parse_date(s: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None
