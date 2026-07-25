"""Регистър на провайдърите за подаване.

Активният провайдър се избира с настройка `NRA_SUBMISSION_PROVIDER`. По подразбиране е
пакетът за ръчно подаване — единственият, който работи днес. Когато НАП публикува
официален API, се сменя само настройката.
"""
from __future__ import annotations

from app.core.config import settings
from app.tax_engine.submission.base import NraSubmissionProvider
from app.tax_engine.submission.providers import (
    NraPortalPackageProvider,
    NraSaftApiProvider,
    NraSocialDeclarationsProvider,
    NraVatApiProvider,
)

_PROVIDERS: dict[str, NraSubmissionProvider] = {}


def register(provider: NraSubmissionProvider) -> None:
    _PROVIDERS[provider.code] = provider


def get_submission_provider(code: str | None = None) -> NraSubmissionProvider:
    key = code or settings.NRA_SUBMISSION_PROVIDER
    provider = _PROVIDERS.get(key)
    if provider is None:
        raise ValueError(f"Няма регистриран провайдър за подаване с код {key!r}")
    return provider


def available_providers() -> list[NraSubmissionProvider]:
    return list(_PROVIDERS.values())


for _p in (
    NraPortalPackageProvider(),
    NraVatApiProvider(),
    NraSaftApiProvider(),
    NraSocialDeclarationsProvider(),
):
    register(_p)
