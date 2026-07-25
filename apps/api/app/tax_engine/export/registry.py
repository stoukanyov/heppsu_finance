"""Регистър на експортните провайдъри (versioned export providers).

Един и същ отчет може да има няколко версии на формата (различни години, различни схеми
на НАП). Регистърът пази всички и позволява избор по код или по код+версия.
"""
from __future__ import annotations

from app.tax_engine.export.base import ExportProvider
from app.tax_engine.export.saft import SaftBgV1Provider
from app.tax_engine.export.ubl import UblBisBillingProvider

_PROVIDERS: dict[tuple[str, str], ExportProvider] = {}
_LATEST: dict[str, ExportProvider] = {}


def register(provider: ExportProvider) -> None:
    _PROVIDERS[(provider.code, provider.version)] = provider
    current = _LATEST.get(provider.code)
    if current is None or provider.version > current.version:
        _LATEST[provider.code] = provider


def get_export_provider(code: str, version: str | None = None) -> ExportProvider:
    if version is not None:
        provider = _PROVIDERS.get((code, version))
        if provider is None:
            raise ValueError(f"Няма експортен провайдър {code!r} версия {version!r}")
        return provider
    provider = _LATEST.get(code)
    if provider is None:
        raise ValueError(f"Няма регистриран експортен провайдър {code!r}")
    return provider


def available_export_providers() -> list[ExportProvider]:
    return list(_PROVIDERS.values())


register(SaftBgV1Provider())
register(UblBisBillingProvider())
