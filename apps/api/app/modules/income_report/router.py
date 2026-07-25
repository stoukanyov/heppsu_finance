"""API рутер за Справката по чл. 73, ал. 6 от ЗДДФЛ (tenant-scoped).

Генерира готовия за подаване в НАП XML файл SPR73_6.xml. Системата само подготвя
файла — не го подава (подаването е само по електронен път през портала на НАП).
"""
from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.income_report import generator
from app.modules.income_report.schemas import (
    Chl736Payer,
    Chl736Report,
    validate_correction_codes,
)

router = APIRouter(prefix="/income-reports", tags=["income-reports"])


@router.post("/chl73-6/xml", dependencies=[require("reports.export")])
def generate_chl73_6(report: Chl736Report, ctx: CurrentCompany, db: DbSession) -> Response:
    """Генерира SPR73_6.xml от подадените данни за изплатени доходи по трудови правоотношения."""
    # Платецът по подразбиране е текущата компания (ако не е подаден изрично).
    if report.payer is None:
        company = ctx.company
        if not company.eik:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Компанията няма попълнен ЕИК — задайте платец (payer) в заявката.",
            )
        report.payer = Chl736Payer(eik=company.eik, name=company.name)

    errors = validate_correction_codes(report.persons)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    xml_bytes = generator.build_xml(report)
    return Response(
        content=xml_bytes,
        media_type="application/xml; charset=windows-1251",
        headers={"Content-Disposition": 'attachment; filename="SPR73_6.xml"'},
    )


@router.post("/chl73-6/validate", dependencies=[require("reports.export")])
def validate_chl73_6(report: Chl736Report, ctx: CurrentCompany, db: DbSession) -> dict:
    """Сверява файла със схемата SPR73_6.xsd на НАП, преди да бъде подаден.

    Схемата е в репото, затова проверката е формална и пълна — грешките идват с
    път в документа.
    """
    if report.payer is None:
        company = ctx.company
        if not company.eik:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Компанията няма попълнен ЕИК — задайте платец (payer) в заявката.",
            )
        report.payer = Chl736Payer(eik=company.eik, name=company.name)

    result = generator.validate_xml(generator.build_xml(report))
    return {
        "target": result.target,
        "ok": result.ok,
        "summary": result.summary(),
        "schema_name": result.schema_name,
        "schema_present": result.schema_present,
        "errors": [{"message": i.message, "path": i.path, "line": i.line} for i in result.errors],
        "warnings": [{"message": i.message, "path": i.path} for i in result.warnings],
    }
