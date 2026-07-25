"""Export Engine — абстракция за форматите на изходните файлове.

Принцип (виж docs/ARCHITECTURE-TAX-ENGINE.md): Export Engine НЕ съдържа бизнес логика.
Той само преобразува вече изчислени данни в конкретен формат. Така форматът на НАП може
да се сменя (TXT → XML → SAF-T → REST API), без промяна в счетоводното ядро.

`IExportProvider` е договорът; всяка реализация декларира версия, за да може един и същ
отчет да се подава в различни години с различни схеми.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.companies.models import Company


@dataclass
class ExportResult:
    """Готов за запис/подаване файл."""

    filename: str
    content: bytes
    media_type: str = "application/xml"
    encoding: str = "utf-8"
    contents: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ExportProvider(ABC):
    """`IExportProvider` — договор за формат на експорт."""

    code: str
    name: str
    version: str          # версия на схемата/формата (напр. „1.0.0" за SAF-T BG)
    media_type: str = "application/xml"

    @abstractmethod
    def export(self, company: "Company", context: dict) -> ExportResult:
        """Преобразува подадените данни в конкретния формат."""
        raise NotImplementedError
