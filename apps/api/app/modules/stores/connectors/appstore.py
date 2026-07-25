"""Apple App Store Connect — конектор за Sales and Trends отчети.

Автентикация: JWT (ES256), подписан с частния ключ .p8 (виж настройките APPLE_*).
Изтегля дневните SALES/SUMMARY отчети (gzip TSV) и ги нормализира. Изисква
`cryptography` за ES256 подпис; при липса се вдига ясна грешка (по подразбиране се
ползва stub конекторът, докато няма credentials).
"""
from __future__ import annotations

import datetime as dt
import functools
import gzip
import io
import time
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
from app.modules.stores.models import StorePlatform, StoreProductType

_API = "https://api.appstoreconnect.apple.com/v1/salesReports"
_AUDIENCE = "appstoreconnect-v1"


def _product_type(code: str) -> StoreProductType:
    code = (code or "").upper()
    if code.startswith("IA"):
        return StoreProductType.IN_APP
    if "SUBSCRIPTION" in code or code in ("F1", "IAY", "IAC"):
        return StoreProductType.SUBSCRIPTION
    return StoreProductType.APP


class AppStoreConnector(StoreConnector):
    platform = StorePlatform.APP_STORE

    def _jwt(self) -> str:
        import jwt  # PyJWT

        with open(settings.APPLE_PRIVATE_KEY_PATH, "r", encoding="utf-8") as fh:
            private_key = fh.read()
        now = int(time.time())
        payload = {"iss": settings.APPLE_ISSUER_ID, "iat": now, "exp": now + 900, "aud": _AUDIENCE}
        headers = {"kid": settings.APPLE_KEY_ID, "typ": "JWT"}
        return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    def _fetch_day(self, client, token: str, day: dt.date) -> list[StoreSaleData]:
        params = {
            "filter[frequency]": "DAILY",
            "filter[reportType]": "SALES",
            "filter[reportSubType]": "SUMMARY",
            "filter[vendorNumber]": settings.APPLE_VENDOR_NUMBER,
            "filter[reportDate]": day.isoformat(),
            "filter[version]": "1_0",
        }
        resp = client.get(
            _API, params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/a-gzip"},
            timeout=60,
        )
        if resp.status_code == 404:
            return []  # няма отчет за деня (напр. без продажби)
        resp.raise_for_status()
        raw = gzip.GzipFile(fileobj=io.BytesIO(resp.content)).read().decode("utf-8")
        return self._parse_tsv(raw, day)

    def _parse_tsv(self, text: str, day: dt.date) -> list[StoreSaleData]:
        lines = text.splitlines()
        if not lines:
            return []
        header = lines[0].split("\t")
        col = {name: i for i, name in enumerate(header)}

        def field(fields: list[str], name: str, default: str = "") -> str:
            """Колона по име; липсващите колони не чупят реда."""
            i = col.get(name)
            return fields[i] if i is not None and i < len(fields) else default

        rows: list[StoreSaleData] = []
        for line in lines[1:]:
            f = line.split("\t")
            if len(f) < len(header):
                continue
            g = functools.partial(field, f)

            try:
                units = int(g("Units", "0") or 0)
                proceeds = Decimal(g("Developer Proceeds", "0") or "0") * units
            except (ValueError, InvalidOperation):
                continue
            rows.append(
                StoreSaleData(
                    platform=self.platform,
                    report_date=day,
                    app_name=g("Title") or g("SKU"),
                    app_identifier=g("SKU"),
                    country=(g("Country Code") or "")[:2],
                    units=units,
                    proceeds=proceeds.quantize(Decimal("0.01")),
                    currency=(g("Currency of Proceeds") or "USD")[:3],
                    product_type=_product_type(g("Product Type Identifier")),
                )
            )
        return rows

    def fetch_sales(self, date_from: dt.date, date_to: dt.date) -> list[StoreSaleData]:
        import httpx

        token = self._jwt()
        out: list[StoreSaleData] = []
        with httpx.Client() as client:
            day = date_from
            while day <= date_to:
                out.extend(self._fetch_day(client, token, day))
                day += dt.timedelta(days=1)
        return out
