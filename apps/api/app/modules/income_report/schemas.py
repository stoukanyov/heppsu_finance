"""Схеми за Справката по чл. 73, ал. 6 от ЗДДФЛ (изплатени доходи по трудови
правоотношения). Полетата съответстват 1:1 на таговете в XML схемата SPR73_6.xsd
на НАП (Заповед № З-ЦУ-1877/05.12.2019 г.).
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class Chl736Payer(BaseModel):
    """Част I — идентификационни данни за платеца на дохода (работодателя)."""

    eik: str = Field(min_length=9, max_length=10)          # ЕИК/Сл. № от регистъра на НАП
    name: str = Field(min_length=1, max_length=200)        # наименование
    phone: str | None = Field(default=None, max_length=20)
    mail: str | None = Field(default=None, max_length=200)
    reprname: str | None = Field(default=None, max_length=600)   # представляващ — имена
    reprident: str | None = Field(default=None, min_length=10, max_length=10)  # ЕГН/ЛН на представляващия


class Chl736IncomeLine(BaseModel):
    """Част II, т.8 — ред за изплатен код доход и работодател, изплатил дохода."""

    incomecode: str = Field(min_length=3, max_length=3)    # код на дохода (напр. 101, 103)
    employereik: str = Field(min_length=9, max_length=10)  # ЕИК на работодателя, изплатил дохода
    employername: str = Field(min_length=1, max_length=200)
    income: Decimal = Field(ge=0, max_digits=15, decimal_places=2)      # облагаем доход
    advancetax: Decimal = Field(ge=0, max_digits=15, decimal_places=2)  # авансов данък по чл. 42
    healthinsbg: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    healthinsforeign: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductiondisabled: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionins: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionhealthins: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    eiktransfrom: str | None = Field(default=None, min_length=9, max_length=10)  # ЕИК на преобразуващото се предприятие


class Chl736TaxBase49(BaseModel):
    """Част II, ред 8.3 — годишно преизчисление по чл. 49 (само осн. работодател)."""

    taxbase: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    taxreductiondisabled: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionins: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionhealthins: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionretire: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductiondonation01: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductiondonation02: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductiondonation03: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionchildren: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxreductionchildrendisab: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    taxbase491: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    tax: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    diff18: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)  # единственото поле, което допуска отрицателна стойност
    sum19deducted: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    sum19refund: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)


class Chl736Person(BaseModel):
    """Част II — данни за едно физическо лице (ред в справката)."""

    correctioncode: int = Field(ge=0, le=8)                # 0 основни, 1 коригиращи, 8 заличаващи
    firstname: str = Field(min_length=1, max_length=200)
    secondname: str | None = Field(default=None, max_length=200)
    thirdname: str = Field(min_length=1, max_length=200)
    identtype: int = Field(ge=0, le=1)                     # 0 ЕГН, 1 ЛНЧ/ЛН/Сл. №
    ident: str = Field(min_length=9, max_length=10)
    ismainemployer: int = Field(ge=0, le=1)                # 1 работодател по основно ТПО към 31.12
    income_lines: list[Chl736IncomeLine] = Field(min_length=1)
    taxbase251: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    taxbase253: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    taxbase49: Chl736TaxBase49 | None = None
    sumtaxdeducted: Decimal = Field(ge=0, max_digits=15, decimal_places=2)  # общ размер на удържания данък


class Chl736Report(BaseModel):
    """Пълна Справка по чл. 73, ал. 6 от ЗДДФЛ за една година."""

    year: int = Field(ge=2019)
    isterm: int | None = Field(default=None, ge=0, le=1)   # подаване при заличаване/прекратяване (чл.162 ЗКПО)
    payer: Chl736Payer | None = None                       # ако е None — попълва се от компанията
    persons: list[Chl736Person] = Field(min_length=1)


def validate_correction_codes(persons: list[Chl736Person]) -> list[str]:
    """Проверки по реда на НАП: не се смесват основни/коригиращи/заличаващи за едно лице
    в един файл; ключ за съвпадение = (identtype, ident, ismainemployer)."""
    errors: list[str] = []
    seen: dict[tuple, set[int]] = {}
    for p in persons:
        key = (p.identtype, p.ident, p.ismainemployer)
        seen.setdefault(key, set()).add(p.correctioncode)
    for (_identtype, ident, _main), codes in seen.items():
        if len(codes) > 1:
            errors.append(
                f"Лице {ident}: в един файл не се допуска смесване на основни/коригиращи/"
                f"заличаващи данни (кодове {sorted(codes)})."
            )
    return errors
