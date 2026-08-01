"""BulgariaTaxProvider — данъчният плъгин за България (режим ЗДДС / НАП).

Първа стъпка от изнасянето на данъчната логика от счетоводното ядро (Strangler-Fig):
провайдърът е новият собственик на българската данъчна логика. Днес той делегира към
`app/modules/vat/nap_export.py` (класификация на сделки, клетки на справка-декларацията,
файлове POKUPKI/PRODAGBI/DEKLAR/VIES). При следваща итерация тази логика се пренася
физически тук, без промяна в ядрото или в договора `TaxProvider`.
"""
from __future__ import annotations

from app.modules.companies.models import Company
from app.modules.vat import nap_export
from app.modules.vat.models import VatEntry
from app.modules.vat.nap_export import DeclarationCells
from app.tax_engine.base import TaxJurisdiction, TaxProvider
from app.tax_engine.export.validation import ValidationReport


class BulgariaTaxProvider(TaxProvider):
    jurisdiction = TaxJurisdiction(
        code="BG-NRA",
        name="България — НАП (ЗДДС)",
        country="BG",
        # България е в еврозоната от 01.01.2026 — левът не съществува. Историческите
        # суми до 31.12.2025 се преизчисляват по фиксирания курс 1 EUR = 1,95583 BGN.
        currency="EUR",
    )

    def compute_declaration(self, entries: list[VatEntry]) -> DeclarationCells:
        return nap_export.compute_declaration_cells(entries)

    def build_filing_package(
        self, company: Company, period_code: str, entries: list[VatEntry]
    ) -> tuple[bytes, DeclarationCells]:
        return nap_export.build_nap_zip(company, period_code, entries)

    def validate_filing_package(
        self, company: Company, period_code: str, entries: list[VatEntry]
    ) -> ValidationReport:
        return nap_export.validate_nap_files(company, period_code, entries)

    @property
    def filing_filename(self) -> str:
        return "NAP-DDS.zip"
