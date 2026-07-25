"""Провайдъри за подаване към НАП.

Наличен днес:
- `NraPortalPackageProvider` — подготвя пакет за ръчно качване в портала на НАП.

Подготвени за бъдещето (вдигат ясна грешка, докато НАП не публикува спецификация):
- `NraVatApiProvider` — официален API за справка-декларацията по ЗДДС
- `NraSaftApiProvider` — подаване на SAF-T
- `NraSocialDeclarationsProvider` — декларации 1 и 6 (осигуряване)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.tax_engine.submission.base import (
    NraSubmissionProvider,
    SubmissionCapability,
    SubmissionPackage,
)

if TYPE_CHECKING:
    from app.modules.companies.models import Company

NRA_PORTAL_URL = "https://portal.nra.bg/"


class NraPortalPackageProvider(NraSubmissionProvider):
    """Подготвя пакет файлове за ръчно подаване през портала на НАП.

    Не подава и не имитира действия в портала: подписването с КЕП и самото подаване
    се извършват от законния представител или упълномощено лице.
    """

    code = "NRA_PORTAL_PACKAGE"
    name = "НАП портал — пакет за ръчно подаване"
    capabilities = (SubmissionCapability.PREPARE_PACKAGE,)
    portal_url = NRA_PORTAL_URL

    def prepare_package(
        self, company: "Company", period_code: str, payload: bytes, contents: list[str]
    ) -> SubmissionPackage:
        ident = (company.vat_number or company.eik or "NOVAT").replace(" ", "")
        return SubmissionPackage(
            filename=f"NAP-DDS-{ident}-{period_code}.zip",
            content=payload,
            contents=contents,
            period_code=period_code,
            instructions=[
                "Влез в портала на НАП с КЕП (Е-услуги → Декларации по ЗДДС).",
                "Качи файловете от пакета за съответния данъчен период.",
                "Подпиши с КЕП и подай — подаването е до 14-о число на следващия месец.",
                "Свали разписката/протокола и я импортирай тук с „Импортирай разписка“.",
            ],
        )


class _FutureApiProvider(NraSubmissionProvider):
    """Общ родител за провайдърите, които чакат официален API на НАП."""

    capabilities = (
        SubmissionCapability.PREPARE_PACKAGE,
        SubmissionCapability.SUBMIT_ELECTRONICALLY,
        SubmissionCapability.FETCH_STATUS,
        SubmissionCapability.FETCH_RECEIPT,
    )
    portal_url = NRA_PORTAL_URL

    def prepare_package(
        self, company: "Company", period_code: str, payload: bytes, contents: list[str]
    ) -> SubmissionPackage:
        return SubmissionPackage(
            filename=f"{self.code}-{period_code}.zip",
            content=payload,
            contents=contents,
            period_code=period_code,
        )

    def submit(self, company: "Company", package: SubmissionPackage) -> dict:
        raise NotImplementedError(
            f"{self.name}: изчаква официална спецификация на НАП (тестова среда, "
            "автентикация, статуси и протоколи за приемане). Ползвай пакета за ръчно подаване."
        )


class NraVatApiProvider(_FutureApiProvider):
    code = "NRA_VAT_API"
    name = "НАП API — справка-декларация по ЗДДС (бъдещ)"


class NraSaftApiProvider(_FutureApiProvider):
    code = "NRA_SAFT_API"
    name = "НАП API — SAF-T (бъдещ)"


class NraSocialDeclarationsProvider(_FutureApiProvider):
    code = "NRA_SOCIAL_API"
    name = "НАП API — декларации 1 и 6 (бъдещ)"
