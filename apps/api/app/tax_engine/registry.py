"""Регистър и discovery на данъчните провайдъри (Tax Providers).

Ядрото избира провайдър по държавата на компанията чрез `get_provider(country)`.
Добавянето на нова юрисдикция = регистриране на нов `TaxProvider` тук, без промяна на
викащия код. Това прави продукта международна платформа, а не само български софтуер.
"""
from __future__ import annotations

from app.tax_engine.base import TaxProvider
from app.tax_engine.providers.bulgaria import BulgariaTaxProvider

_PROVIDERS: dict[str, TaxProvider] = {}
_DEFAULT_COUNTRY = "BG"


def register(provider: TaxProvider) -> None:
    _PROVIDERS[provider.jurisdiction.country.upper()] = provider


def get_provider(country: str | None) -> TaxProvider:
    """Връща данъчния провайдър за държавата (fallback към България)."""
    key = (country or _DEFAULT_COUNTRY).upper()
    provider = _PROVIDERS.get(key) or _PROVIDERS.get(_DEFAULT_COUNTRY)
    if provider is None:  # pragma: no cover - при регистриран BG не се случва
        raise ValueError(f"Няма регистриран данъчен провайдър за държава {key!r}")
    return provider


def available_providers() -> list[TaxProvider]:
    return list(_PROVIDERS.values())


# Регистрация на вградените провайдъри при импорт на модула.
register(BulgariaTaxProvider())
