"""Абстракция за подаване към НАП — `INraSubmissionProvider`.

Днес подаването е ръчно: системата ГЕНЕРИРА пакет файлове, а потребителят влиза в
портала на НАП, качва ги и ги подписва с КЕП. Затова наличният провайдър е
`NraPortalPackageProvider` — той подготвя пакет, но НЕ подава.

Когато НАП публикува официален API (със спецификация, тестова среда, автентикация и
протоколи за приемане), се добавя нов провайдър, без промяна в Tax Engine и в
счетоводното ядро.

СЪЗНАТЕЛНО РЕШЕНИЕ (D-012): не се реализира автоматизация чрез робот, който имитира
кликове в портала. Такъв подход е нестабилен, зависи от интерфейса и е рисков при
юридически значимо подаване.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.companies.models import Company


class SubmissionCapability:
    """Какво може даден провайдър."""

    PREPARE_PACKAGE = "PREPARE_PACKAGE"      # генерира файлове за ръчно качване
    SUBMIT_ELECTRONICALLY = "SUBMIT"         # подава по електронен път (бъдещ API)
    FETCH_STATUS = "FETCH_STATUS"            # проверява статус на подаването
    FETCH_RECEIPT = "FETCH_RECEIPT"          # изтегля разписка/протокол


@dataclass
class SubmissionPackage:
    """Готов за подаване пакет (един файл, обикновено ZIP)."""

    filename: str
    content: bytes
    media_type: str = "application/zip"
    # Кои документи съдържа — за прегледа преди подаване.
    contents: list[str] = field(default_factory=list)
    period_code: str = ""
    instructions: list[str] = field(default_factory=list)


class NraSubmissionProvider(ABC):
    """Договор за подаване на данъчни декларации (`INraSubmissionProvider`)."""

    code: str
    name: str
    capabilities: tuple[str, ...] = (SubmissionCapability.PREPARE_PACKAGE,)
    portal_url: str | None = None

    @abstractmethod
    def prepare_package(
        self, company: "Company", period_code: str, payload: bytes, contents: list[str]
    ) -> SubmissionPackage:
        """Оформя пакета за подаване (име на файл, съдържание, инструкции)."""
        raise NotImplementedError

    def submit(self, company: "Company", package: SubmissionPackage) -> dict:
        """Електронно подаване — налично само при провайдър с такава възможност."""
        raise NotImplementedError(
            f"Провайдърът „{self.name}“ не поддържа електронно подаване. "
            "Подаването се извършва ръчно в портала на НАП с КЕП."
        )

    def fetch_status(self, company: "Company", reference: str) -> dict:
        raise NotImplementedError(
            f"Провайдърът „{self.name}“ не поддържа проверка на статус."
        )

    @property
    def supports_electronic_submission(self) -> bool:
        return SubmissionCapability.SUBMIT_ELECTRONICALLY in self.capabilities

    def deadline_for(self, period_end: dt.date, day: int = 14) -> dt.date:
        """Срок за подаване: до `day`-о число на месеца след периода."""
        day_after = period_end + dt.timedelta(days=1)
        return dt.date(day_after.year, day_after.month, day)
