"""Контракт за конекторите към банки (PSD2 / open banking).

Огледално на `StoreConnector`: ядрото на модула `banking` работи само през този
договор, така че източникът на движения е взаимозаменяем плъгин — агрегатор,
директен API на банка или stub за тестове. Файловият импорт (CSV/MT940/CAMT)
остава непокътнат; това е допълнителен път, не замяна.

Данните излизат нормализирани в `BankTransactionIn` — същия вход, който ползва
файловият импорт. Така дедупликацията и автоматичното съпоставяне са едни и същи
за двата пътя и не могат да се разминат.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.modules.banking.schemas import BankTransactionIn


@dataclass
class RemoteAccount:
    """Сметка, върната от доставчика при свързване."""

    external_id: str
    iban: str | None = None
    name: str | None = None
    currency: str | None = None
    owner_name: str | None = None


@dataclass
class ConsentSession:
    """Заявка за съгласие: линк, на който потребителят се удостоверява пред банката си."""

    external_id: str                 # идентификатор на съгласието при доставчика
    link: str                        # URL, който потребителят отваря
    expires_at: dt.datetime | None = None
    institution_name: str | None = None


@dataclass
class Institution:
    """Банка, налична при доставчика."""

    external_id: str
    name: str
    country: str = "BG"
    logo: str | None = None
    max_consent_days: int = 90


@dataclass
class FetchResult:
    transactions: list[BankTransactionIn] = field(default_factory=list)
    fetched_from: dt.date | None = None
    fetched_to: dt.date | None = None
    warnings: list[str] = field(default_factory=list)


class BankConnector(ABC):
    """`IBankConnector` — договор за източник на банкови движения."""

    code: str
    name: str
    #: Изисква ли периодично подновяване на съгласието (PSD2 — да).
    requires_consent_renewal: bool = True

    @property
    def available(self) -> bool:
        """Има ли конфигурирани credentials. Липсата им НЕ е изключение при старт."""
        return True

    @abstractmethod
    def list_institutions(self, country: str = "BG") -> list[Institution]:
        """Банките, които доставчикът поддържа за държавата."""
        raise NotImplementedError

    @abstractmethod
    def start_consent(self, institution_id: str, redirect_url: str) -> ConsentSession:
        """Започва съгласие — връща линк, който потребителят отваря пред банката си."""
        raise NotImplementedError

    @abstractmethod
    def list_accounts(self, consent_external_id: str) -> list[RemoteAccount]:
        """Сметките, до които съгласието дава достъп."""
        raise NotImplementedError

    @abstractmethod
    def fetch_transactions(
        self, account_external_id: str, date_from: dt.date, date_to: dt.date
    ) -> FetchResult:
        """Изтегля движенията за периода, нормализирани като `BankTransactionIn`."""
        raise NotImplementedError
