"""Избор на банков конектор: реален (при налични credentials) или stub."""
from __future__ import annotations

from app.modules.banking.connectors.base import BankConnector
from app.modules.banking.connectors.gocardless import GoCardlessBankConnector
from app.modules.banking.connectors.stub import StubBankConnector

_STUB = StubBankConnector()
_LIVE = GoCardlessBankConnector()


def get_bank_connector(code: str | None = None) -> BankConnector:
    """Връща конектор по код; без код — реалния, ако е конфигуриран, иначе stub."""
    if code == StubBankConnector.code:
        return _STUB
    if code == GoCardlessBankConnector.code:
        return _LIVE
    return _LIVE if _LIVE.available else _STUB


def available_bank_connectors() -> list[BankConnector]:
    return [_LIVE, _STUB]
