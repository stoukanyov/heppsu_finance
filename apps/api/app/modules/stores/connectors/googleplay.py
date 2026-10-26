"""Google Play — конектор за финансовите отчети от Play Console.

Пътят е същият, който вече тегли реални данни в Control Center, затова е описан
точно: Play Console изнася отчетите в кофа в Google Cloud Storage
(`GOOGLE_PLAY_BUCKET`, вида `pubsite_prod_rev_<номер>`), а достъпът е service
account (`GOOGLE_APPLICATION_CREDENTIALS`).

Три неща, в които предишната версия на този файл не можеше да проработи:

1. Четеше `sales/salesreport_YYYYMM.csv`. Отчетът за ПРИХОДИТЕ е
   `earnings/earnings_YYYYMM_<номер на търговеца>-N.zip` — архив с един или
   повече CSV-а, а не един CSV. В нашата кофа има точно earnings файлове;
   `sales/` се появява само когато има платени заявки.
2. Искаше пакета `google-cloud-storage`, който не е зависимост на проекта (и
   го няма в production образа). Тук се ползва JSON API-то на GCS през httpx и
   подписан токен с PyJWT — същите зависимости, с които работи и App Store.
3. Декодираше като UTF-8. Отчетите на Play са **UTF-16LE с BOM** и излизаха
   като безсмислица.

Сумата се чете от `Amount (Merchant Currency)` — тя е нетна: редовете с
`Google fee` и `Tax` идват отрицателни в същия отчет и се събират в същия ден,
приложение и държава, тоест накрая остава това, което реално постъпва.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import time
import zipfile
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from app.core.config import settings
from app.modules.stores.connectors.base import StoreConnector, StoreSaleData
from app.modules.stores.models import StorePlatform, StoreProductType

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — адрес, не тайна
SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
GCS = "https://storage.googleapis.com/storage/v1/b"

# Видове транзакции в отчета. Единици броим само покупките; таксата на Google и
# данъкът са пари без бройка, затова влизат в сумата, но не в количеството.
_POKUPKA = "charge"
_VRASHTANE = "charge refund"


def _product_type(code: str) -> StoreProductType:
    code = (code or "").strip().lower()
    if "subscription" in code or code == "subs":
        return StoreProductType.SUBSCRIPTION
    if "in-app" in code or "inapp" in code or code == "in-app product":
        return StoreProductType.IN_APP
    return StoreProductType.APP


def decode_report(raw: bytes) -> str:
    """Отчетите на Play са UTF-16LE с BOM; пазим и пътя за UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("utf-16", errors="replace")


def _parse_date(s: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%b %d, %Y %H:%M:%S", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _decimal(s: str | None) -> Decimal | None:
    raw = (s or "").replace(",", "").replace(" ", "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


class GooglePlayConnector(StoreConnector):
    platform = StorePlatform.GOOGLE_PLAY

    # ---------------- парсване (без мрежа, затова е тествано самостоятелно) ----

    def parse_csv(self, text: str) -> list[StoreSaleData]:
        """Един CSV от отчет на Play → нормализирани редове.

        Разбира и двата формата, които кофата съдържа; имената на колоните са
        прочетени от живите отчети на 26.10.2026, не предположени:

        earnings (`PlayApps_YYYYMM.csv` в архива, по транзакция)
            Transaction Date · Transaction Type (Charge / Google fee /
            Charge refund) · Package ID · Sku Id · Product Type · Buyer Country ·
            Merchant Currency · Amount (Merchant Currency)

        salesreport (`salesreport_YYYYMM.csv` в архива, по заявка)
            Order Charged Date · Financial Status (Charged / Refund) ·
            Package ID · SKU ID · Country of Buyer · Currency of Sale ·
            Charged Amount

        Приложението е **Package ID**. Нямаше такова четене: кодът търсеше
        „Product id“, каквато колона в отчетите няма, и падаше на Sku Id —
        тоест приходът на Beagle Owner се записваше срещу „plus_monthly“.
        """
        reader = csv.DictReader(io.StringIO(text))
        rows: list[StoreSaleData] = []
        for r in reader:
            red = {(k or "").strip(): (v or "") for k, v in r.items()}
            report_date = _parse_date(
                red.get("Transaction Date")
                or red.get("Order Charged Date")
                or red.get("Order Charged Timestamp")
                or ""
            )
            if report_date is None:
                continue

            # Сумата: нетното постъпление в валутата на търговеца, иначе
            # начислената сума от отчета за продажбите.
            amount = _decimal(red.get("Amount (Merchant Currency)"))
            if amount is None:
                amount = _decimal(red.get("Charged Amount"))
            if amount is None:
                amount = _decimal(red.get("Item Price"))
            if amount is None:
                continue

            vid = (red.get("Transaction Type") or "").strip().lower()
            sostoyanie = (red.get("Financial Status") or "").strip().lower()
            if vid:
                # Отчет за приходите: бройка само за покупка и връщане. Таксата
                # на Google и данъкът са пари без бройка — влизат в сумата, не в
                # количеството, иначе една покупка се брои три пъти.
                units = {_POKUPKA: 1, _VRASHTANE: -1}.get(vid, 0)
            elif sostoyanie:
                # Отчет за продажбите: една заявка е една бройка; връщането я маха.
                units = -1 if "refund" in sostoyanie else 1
            else:
                units = int(_decimal(red.get("Quantity")) or 1)

            paket = (red.get("Package ID") or red.get("Product id") or "").strip()
            sku = (red.get("Sku Id") or red.get("SKU ID") or red.get("Sku ID") or "").strip()
            rows.append(
                StoreSaleData(
                    platform=self.platform,
                    report_date=report_date,
                    app_name=(red.get("Product Title") or paket or sku).strip(),
                    app_identifier=paket or sku,
                    country=(red.get("Buyer Country") or red.get("Country of Buyer") or "")[:2],
                    units=units,
                    proceeds=amount.quantize(Decimal("0.01")),
                    currency=(
                        red.get("Merchant Currency")
                        or red.get("Currency of Sale")
                        or red.get("Buyer Currency")
                        or "EUR"
                    )[:3],
                    product_type=_product_type(
                        red.get("Product Type") or red.get("Product type") or ""
                    ),
                )
            )
        return rows

    def parse_archive(self, raw: bytes) -> list[StoreSaleData]:
        """Отчет от кофата → редове. Архив или самостоятелен CSV.

        И `earnings_YYYYMM_*.zip`, и `salesreport_YYYYMM.zip` са архиви с по
        един CSV вътре (UTF-16). Самостоятелен CSV се допуска, защото Play е
        променял това в миналото.
        """
        if raw[:2] != b"PK":
            return self.parse_csv(decode_report(raw))
        out: list[StoreSaleData] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.namelist():
                if not member.lower().endswith(".csv"):
                    continue
                out.extend(self.parse_csv(decode_report(zf.read(member))))
        return out

    def months(self, date_from: dt.date, date_to: dt.date) -> list[str]:
        meseci, cur = [], dt.date(date_from.year, date_from.month, 1)
        while cur <= date_to:
            meseci.append(cur.strftime("%Y%m"))
            cur = dt.date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
        return meseci

    # ---------------- мрежа --------------------------------------------------

    def _access_token(self) -> str:
        import json

        import jwt  # PyJWT[crypto] — RS256

        with open(settings.GOOGLE_APPLICATION_CREDENTIALS, encoding="utf-8") as fh:
            info = json.loads(fh.read())
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": info["client_email"],
                "scope": SCOPE,
                "aud": TOKEN_URL,
                "iat": now,
                "exp": now + 3600,
            },
            info["private_key"],
            algorithm="RS256",
        )
        import httpx

        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _list(self, client, bucket: str, prefix: str) -> list[str]:
        names: list[str] = []
        page: str | None = None
        while True:
            params: dict = {"prefix": prefix, "maxResults": 500}
            if page:
                params["pageToken"] = page
            resp = client.get(f"{GCS}/{bucket}/o", params=params)
            if resp.status_code == 404:
                return names
            resp.raise_for_status()
            payload = resp.json()
            names.extend(item["name"] for item in payload.get("items", []))
            page = payload.get("nextPageToken")
            if not page:
                return names

    def _download(self, client, bucket: str, obj: str) -> bytes | None:
        resp = client.get(f"{GCS}/{bucket}/o/{quote(obj, safe='')}", params={"alt": "media"})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    def fetch_sales(self, date_from: dt.date, date_to: dt.date) -> list[StoreSaleData]:
        import httpx

        bucket = settings.GOOGLE_PLAY_BUCKET
        token = self._access_token()
        out: list[StoreSaleData] = []
        with httpx.Client(
            headers={"Authorization": f"Bearer {token}"}, timeout=60
        ) as client:
            for ym in self.months(date_from, date_to):
                imashe_earnings = False
                for name in self._list(client, bucket, f"earnings/earnings_{ym}"):
                    raw = self._download(client, bucket, name)
                    if raw:
                        imashe_earnings = True
                        out.extend(self.parse_archive(raw))
                if imashe_earnings:
                    # Двата отчета описват ЕДНИ И СЪЩИ пари от различни страни:
                    # earnings е нетното постъпление, salesreport — начисленото.
                    # Четени заедно, приходите за месеца се удвояват.
                    continue
                # Отчетът за приходите излиза СЛЕД края на месеца, затова за
                # текущия месец единственото, което съществува, е отчетът за
                # продажбите. Името се търси с изброяване: файлът е
                # `sales/salesreport_YYYYMM.zip`, а предишната версия на този код
                # теглеше `.csv` — тоест 404 и нула реда за текущия месец.
                for name in self._list(client, bucket, f"sales/salesreport_{ym}"):
                    raw = self._download(client, bucket, name)
                    if raw:
                        out.extend(self.parse_archive(raw))
        return [r for r in out if date_from <= r.report_date <= date_to]
