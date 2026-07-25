"""Схеми за календара със сроковете. Контрактът се ползва от мобилното приложение."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

# Категории (стабилни стойности — мобилният клиент филтрира и оцветява по тях).
CATEGORY_VAT = "VAT"
CATEGORY_PAYROLL = "PAYROLL"
CATEGORY_CORPORATE_TAX = "CORPORATE_TAX"
CATEGORY_STATISTICS = "STATISTICS"
CATEGORY_ANNUAL_REPORT = "ANNUAL_REPORT"

# Институции
AUTHORITY_NAP = "НАП"
AUTHORITY_NSI = "НСИ"
AUTHORITY_TR = "Търговски регистър"


class DeadlineOut(BaseModel):
    """Един срок за подаване/плащане, вече изместен до работен ден."""

    key: str = Field(description='Стабилен идентификатор, напр. "vat-return:2026-07"')
    title: str                      # кратко заглавие за списъка
    description: str                # какво точно се подава/плаща
    due_date: dt.date               # крайният срок след преместването (работен ден)
    original_due_date: dt.date      # законовата дата преди преместването
    moved_for_holiday: bool         # True, ако е изместен заради уикенд/празник
    period_label: str               # за кой период е, напр. „юни 2026“ / „2025 г.“
    category: str                   # VAT | PAYROLL | CORPORATE_TAX | STATISTICS | ANNUAL_REPORT
    authority: str                  # НАП | НСИ | Търговски регистър
    conditional: bool               # True = важи само при определени обстоятелства
    conditional_note: str | None = None  # кога важи, напр. „ако има ВОД за периода“
    days_remaining: int             # спрямо reference_date; отрицателно = просрочен
    filed: bool = False             # отметнат като подаден
    filed_at: dt.datetime | None = None


class FilingRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class FilingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    filed_at: dt.datetime
    note: str | None
