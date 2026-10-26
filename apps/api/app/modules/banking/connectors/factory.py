"""Избор на банков конектор: реален, подставен или никакъв.

Нямаше трети вариант: без credentials системата връщаше подставения конектор —
„УниКредит Булбанк (демо)“ с измислени движения по 120,50 EUR, които влизат в
истинския дневник и в съпоставянето. Затова „няма ключове“ вече е ясна грешка
(`BankNotConnected`), а подставеният конектор иска изрично `BANK_PROVIDER=stub`
и е забранен в production.
"""
from __future__ import annotations

from app.core.config import settings
from app.modules.banking.connectors.base import BankConnector
from app.modules.banking.connectors.gocardless import GoCardlessBankConnector
from app.modules.banking.connectors.stub import StubBankConnector

NUZHNI_NASTROYKI = "GOCARDLESS_SECRET_ID и GOCARDLESS_SECRET_KEY"

_STUB = StubBankConnector()
_LIVE = GoCardlessBankConnector()


class BankNotConnected(RuntimeError):
    """Няма банков доставчик — не връщаме подставени движения вместо това."""

    def __init__(self) -> None:
        super().__init__(
            "Банковата връзка не е настроена. За реални сметки и движения задай "
            f"в средата: {NUZHNI_NASTROYKI}. Дотогава движенията се внасят с файл "
            "(CSV, MT940 или camt.053)."
        )


def get_bank_connector(code: str | None = None) -> BankConnector:
    """Конектор по код или по режима от конфигурацията.

    Изричният код от заявката не отваря задна врата: `provider=STUB` в
    production също минава през режима и дава `BankNotConnected`.
    """
    rezhim = settings.bank_provider
    if code == StubBankConnector.code:
        if rezhim != "stub":
            raise BankNotConnected()
        return _STUB
    if code == GoCardlessBankConnector.code:
        if not _LIVE.available:
            raise BankNotConnected()
        return _LIVE
    if rezhim == "live":
        return _LIVE
    if rezhim == "stub":
        return _STUB
    raise BankNotConnected()


def available_bank_connectors() -> list[BankConnector]:
    """Доставчиците, които екранът може да предложи — без демото в production."""
    if settings.bank_provider == "stub":
        return [_LIVE, _STUB]
    return [_LIVE]
