"""Детерминиран конектор за тестове и демонстрация — без мрежа.

Държи се като реален доставчик (банки, съгласие, сметки, движения), но всичко е
изчислено от входа. Така целият поток се тества без credentials и без интернет.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

from app.modules.banking.connectors.base import (
    BankConnector,
    ConsentSession,
    FetchResult,
    Institution,
    RemoteAccount,
)
from app.modules.banking.schemas import BankTransactionIn

_INSTITUTIONS = [
    Institution("STUB_UNICREDIT", "УниКредит Булбанк (демо)", "BG"),
    Institution("STUB_DSK", "Банка ДСК (демо)", "BG"),
    Institution("STUB_POSTBANK", "Пощенска банка (демо)", "BG"),
]


class StubBankConnector(BankConnector):
    code = "STUB"
    name = "Демонстрационен доставчик (без мрежа)"

    def list_institutions(self, country: str = "BG") -> list[Institution]:
        return [i for i in _INSTITUTIONS if i.country == country]

    def start_consent(self, institution_id: str, redirect_url: str) -> ConsentSession:
        return ConsentSession(
            external_id=f"stub-consent-{institution_id.lower()}",
            link=f"{redirect_url}?stub_consent={institution_id}",
            expires_at=None,
            institution_name=next(
                (i.name for i in _INSTITUTIONS if i.external_id == institution_id), institution_id
            ),
        )

    def list_accounts(self, consent_external_id: str) -> list[RemoteAccount]:
        digest = hashlib.sha256(consent_external_id.encode()).hexdigest()[:8].upper()
        return [
            RemoteAccount(
                external_id=f"stub-acc-{digest}",
                iban=f"BG18RZBB9155{digest}0001",
                name="Разплащателна сметка (демо)",
                currency="EUR",
            )
        ]

    def fetch_transactions(
        self, account_external_id: str, date_from: dt.date, date_to: dt.date
    ) -> FetchResult:
        """Три предвидими движения на месец — достатъчно, за да се види потокът."""
        items: list[BankTransactionIn] = []
        day = date_from
        index = 0
        while day <= date_to:
            if day.day in (5, 15, 25):
                index += 1
                sign = 1 if index % 2 else -1
                amount = (Decimal("120.50") * index).quantize(Decimal("0.01")) * sign
                items.append(
                    BankTransactionIn(
                        booking_date=day,
                        amount=amount,
                        currency="EUR",
                        counterparty_name="Демо контрагент" if sign < 0 else "Демо клиент",
                        reference=f"DEMO-{day:%Y%m%d}-{index}",
                        description="Демонстрационно движение",
                        external_id=f"{account_external_id}-{day:%Y%m%d}-{index}",
                    )
                )
            day += dt.timedelta(days=1)
        return FetchResult(transactions=items, fetched_from=date_from, fetched_to=date_to)
