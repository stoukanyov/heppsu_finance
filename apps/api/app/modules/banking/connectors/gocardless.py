"""GoCardless Bank Account Data (бивш Nordigen) — AIS доставчик по PSD2.

Избран за първи реален конектор по три причини: покрива българските банки, има
безплатно ниво, достатъчно за пилот, и не изисква собствен PSD2 лиценз — той е
лицензираният посредник, а ние сме негов клиент.

Credentials се четат САМО от средата (D-009): `GOCARDLESS_SECRET_ID` и
`GOCARDLESS_SECRET_KEY`. Липсата им не чупи стартирането — конекторът просто не е
`available` и системата ползва stub-а.

Потокът по PSD2 е задължително двустъпков: първо потребителят се удостоверява пред
СВОЯТА банка (никакви банкови пароли не минават през нас), после доставчикът ни дава
достъп до движенията за срока на съгласието — оттам и подновяването.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.modules.banking.connectors.base import (
    BankConnector,
    ConsentSession,
    FetchResult,
    Institution,
    RemoteAccount,
)
from app.modules.banking.schemas import BankTransactionIn

_BASE = "https://bankaccountdata.gocardless.com/api/v2"
_TIMEOUT = 30


class GoCardlessBankConnector(BankConnector):
    code = "GOCARDLESS"
    name = "GoCardless Bank Account Data (PSD2)"
    requires_consent_renewal = True

    def __init__(self) -> None:
        self._token: str | None = None

    # ------------------------------------------------------------------ основа
    @property
    def available(self) -> bool:
        return bool(settings.GOCARDLESS_SECRET_ID and settings.GOCARDLESS_SECRET_KEY)

    def _require_credentials(self) -> None:
        if not self.available:
            raise RuntimeError(
                "Липсват credentials за GoCardless. Задай GOCARDLESS_SECRET_ID и "
                "GOCARDLESS_SECRET_KEY в средата (не в кода) и рестартирай."
            )

    def _call(self, path: str, *, method: str = "GET", body: dict | None = None,
              auth: bool = True) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        # S310: `_BASE` е константа в модула („https://…“), а `path` се задава от
        # методите тук — потребителски вход не участва в адреса и схемата не може
        # да стане `file:`.
        req = urllib.request.Request(_BASE + path, data=data, method=method)  # noqa: S310
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self._access_token()}")
        try:
            # URL-ът е `_BASE + path`, а `_BASE` е константа в модула — схемата е
            # фиксирана и потребителски вход не участва в адреса.
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as response:  # nosec B310  # noqa: S310
                return json.loads(response.read() or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"GoCardless върна {exc.code} за {path}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Няма връзка с GoCardless: {exc.reason}") from exc

    def _access_token(self) -> str:
        if self._token is None:
            self._require_credentials()
            payload = self._call(
                "/token/new/",
                method="POST",
                auth=False,
                body={
                    "secret_id": settings.GOCARDLESS_SECRET_ID,
                    "secret_key": settings.GOCARDLESS_SECRET_KEY,
                },
            )
            self._token = payload["access"]
        return self._token

    # ------------------------------------------------------------------ договор
    def list_institutions(self, country: str = "BG") -> list[Institution]:
        rows = self._call(f"/institutions/?country={country.lower()}")
        return [
            Institution(
                external_id=row["id"],
                name=row.get("name") or row["id"],
                country=country.upper(),
                logo=row.get("logo"),
                max_consent_days=int(row.get("max_access_valid_for_days") or 90),
            )
            for row in (rows if isinstance(rows, list) else [])
        ]

    def start_consent(self, institution_id: str, redirect_url: str) -> ConsentSession:
        payload = self._call(
            "/requisitions/",
            method="POST",
            body={
                "redirect": redirect_url,
                "institution_id": institution_id,
                "user_language": "BG",
            },
        )
        return ConsentSession(
            external_id=payload["id"],
            link=payload["link"],
            institution_name=institution_id,
        )

    def list_accounts(self, consent_external_id: str) -> list[RemoteAccount]:
        payload = self._call(f"/requisitions/{consent_external_id}/")
        accounts: list[RemoteAccount] = []
        for account_id in payload.get("accounts", []):
            try:
                details = self._call(f"/accounts/{account_id}/details/").get("account", {})
            except RuntimeError:
                details = {}   # някои банки не дават детайли — сметката пак е използваема
            accounts.append(
                RemoteAccount(
                    external_id=account_id,
                    iban=details.get("iban"),
                    name=details.get("name") or details.get("product"),
                    currency=details.get("currency"),
                    owner_name=details.get("ownerName"),
                )
            )
        return accounts

    def fetch_transactions(
        self, account_external_id: str, date_from: dt.date, date_to: dt.date
    ) -> FetchResult:
        payload = self._call(
            f"/accounts/{account_external_id}/transactions/"
            f"?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        )
        rows = (payload.get("transactions") or {})
        items: list[BankTransactionIn] = []
        warnings: list[str] = []

        # Само осчетоводените. Висящите (`pending`) още могат да се променят или отпаднат
        # — внасянето им би създало движения, които после трябва да се трият.
        if rows.get("pending"):
            warnings.append(
                f"{len(rows['pending'])} висящи движения не са внесени — "
                f"ще влязат, след като банката ги осчетоводи."
            )

        for row in rows.get("booked", []):
            parsed = _to_transaction(row)
            if parsed is not None:
                items.append(parsed)
        return FetchResult(
            transactions=items, fetched_from=date_from, fetched_to=date_to, warnings=warnings
        )


def _to_transaction(row: dict) -> BankTransactionIn | None:
    """Нормализира един ред. Различните банки пълнят различни полета — търсим по ред."""
    amount_block = row.get("transactionAmount") or {}
    try:
        amount = Decimal(str(amount_block.get("amount")))
    except (InvalidOperation, TypeError):
        return None

    booking = row.get("bookingDate") or row.get("valueDate")
    if not booking:
        return None
    try:
        booking_date = dt.date.fromisoformat(booking)
    except ValueError:
        return None

    value_date = None
    if row.get("valueDate"):
        try:
            value_date = dt.date.fromisoformat(row["valueDate"])
        except ValueError:
            value_date = None

    description = (
        row.get("remittanceInformationUnstructured")
        or " ".join(row.get("remittanceInformationUnstructuredArray") or [])
        or row.get("additionalInformation")
        or None
    )
    counterparty = row.get("creditorName") if amount < 0 else row.get("debtorName")
    iban_block = row.get("creditorAccount") if amount < 0 else row.get("debtorAccount")

    return BankTransactionIn(
        booking_date=booking_date,
        value_date=value_date,
        amount=amount,
        currency=amount_block.get("currency"),
        counterparty_name=(counterparty or None),
        counterparty_iban=((iban_block or {}).get("iban") if isinstance(iban_block, dict) else None),
        reference=(row.get("endToEndId") or row.get("entryReference") or None),
        description=(description[:500] if description else None),
        # Стабилният идентификатор на банката е основата за дедупликация.
        external_id=(row.get("transactionId") or row.get("internalTransactionId") or None),
    )
