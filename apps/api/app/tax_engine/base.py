"""Ядро на Tax Engine — абстракция, независима от конкретна държава/данъчна власт.

Централен принцип (виж docs/ARCHITECTURE-TAX-ENGINE.md): счетоводното ядро НЕ знае
за НАП или за конкретни данъчни правила. Всяка юрисдикция е плъгин, който имплементира
`TaxProvider` (интерфейсът `ITaxProvider`). България е първият плъгин
(`BulgariaTaxProvider`); по-късно се добавят Румъния, Гърция, Германия и т.н. — без
промяна в ядрото.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # само за типове — без цикъл при импорт
    from app.modules.companies.models import Company
    from app.modules.vat.models import VatEntry
    from app.modules.vat.nap_export import DeclarationCells


@dataclass(frozen=True)
class TaxJurisdiction:
    """Метаданни за данъчна юрисдикция (един данъчен режим)."""

    code: str        # уникален код на провайдъра, напр. "BG-NRA"
    name: str        # човешко име, напр. "България — НАП"
    country: str     # ISO-3166 alpha-2, напр. "BG"
    currency: str    # отчетна валута на режима (информативно)


class TaxProvider(ABC):
    """Интерфейс `ITaxProvider` — договор за данъчен плъгин на една юрисдикция.

    Провайдърът капсулира ВСИЧКО специфично за държавата: класификация на сделките в
    данъчни категории, изчисляване на данъчната декларация и генериране на файловете за
    подаване. Ядрото работи само през този интерфейс.
    """

    jurisdiction: TaxJurisdiction

    @abstractmethod
    def compute_declaration(self, entries: list[VatEntry]) -> DeclarationCells:
        """Агрегира данъчните записи в клетките на периодичната декларация."""
        raise NotImplementedError

    @abstractmethod
    def build_filing_package(
        self, company: Company, period_code: str, entries: list[VatEntry]
    ) -> tuple[bytes, DeclarationCells]:
        """Генерира пакета файлове за подаване (напр. ZIP за НАП) + изчислените клетки."""
        raise NotImplementedError

    @property
    def filing_filename(self) -> str:
        """Име на файла с пакета за подаване (по подразбиране ZIP)."""
        return f"tax-filing-{self.jurisdiction.country}.zip"
