"""Проверка на условията за ускорено възстановяване (чл. 92, ал. 3 ЗДДС).

Основната хипотеза за малки и средни предприятия: за последните 12 месеца преди
текущия данъчен период стойността на доставките с нулева ставка е над 30% от всички
облагаеми доставки. Тук попадат износът към трети държави, вътреобщностните доставки
и определени международни транспортни/спедиторски услуги.

Полученитe авансови плащания НЕ участват в изчисляването на съотношението.

Хипотезата за земеделски производители (над 50% собствена продукция) е с краен срок
31.12.2026 г., затова е конфигурируема, а не закодирана трайно.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.vat.models import VatDirection, VatEntry
from app.modules.vat.nap_export import SaleBucket, classify_sale

ZERO = Decimal("0.00")
LOOKBACK_MONTHS = 12

# Кофи, които се третират като доставки с нулева ставка за целите на чл. 92, ал. 3.
_ZERO_RATE_BUCKETS = (SaleBucket.ICS, SaleBucket.EXPORT, SaleBucket.TRICOUNTRY)

# Документи-аванси не влизат в базата за съотношението.
_ADVANCE_MARKERS = ("аванс", "advance", "предплащане")


@dataclass
class AcceleratedEligibility:
    """Резултат от проверката за ускорено възстановяване."""

    eligible: bool
    zero_rate_amount: Decimal
    taxable_amount: Decimal
    ratio: Decimal              # 0..1
    threshold: Decimal          # изискваният минимум (по подразбиране 0.30)
    period_from: dt.date
    period_to: dt.date
    legal_basis: str = "чл. 92, ал. 3 ЗДДС"
    reasons: list[str] = field(default_factory=list)

    @property
    def ratio_percent(self) -> Decimal:
        return (self.ratio * Decimal("100")).quantize(Decimal("0.1"))


def _is_advance(entry: VatEntry) -> bool:
    text = " ".join(filter(None, (entry.document_type, entry.document_number))).lower()
    return any(marker in text for marker in _ADVANCE_MARKERS)


def zero_rate_ratio(
    db: Session,
    company_id: uuid.UUID,
    as_of: dt.date,
    threshold: Decimal | None = None,
) -> AcceleratedEligibility:
    """Изчислява дела на доставките с нулева ставка за 12-те месеца преди `as_of`."""
    if threshold is None:
        threshold = Decimal(str(settings.VAT_ACCELERATED_ZERO_RATE_THRESHOLD))

    # Прозорецът е 12 месеца, завършващ в месеца ПРЕДИ текущия данъчен период.
    end = as_of.replace(day=1) - dt.timedelta(days=1)
    start_year = end.year - 1
    start_month = end.month + 1
    if start_month > 12:
        start_month -= 12
        start_year += 1
    start = dt.date(start_year, start_month, 1)

    entries = list(
        db.scalars(
            select(VatEntry).where(
                VatEntry.company_id == company_id,
                VatEntry.direction == VatDirection.SALE,
                VatEntry.document_date >= start,
                VatEntry.document_date <= end,
            )
        )
    )

    zero_rate = ZERO
    taxable = ZERO
    for e in entries:
        if _is_advance(e):
            continue
        bucket = classify_sale(e)
        if bucket == SaleBucket.EXEMPT:
            continue  # освободените доставки не са облагаеми
        taxable += e.tax_base
        if bucket in _ZERO_RATE_BUCKETS:
            zero_rate += e.tax_base

    reasons: list[str] = []
    if taxable <= ZERO:
        ratio = ZERO
        reasons.append("Няма облагаеми доставки за периода — съотношението не може да се изчисли.")
    else:
        ratio = (zero_rate / taxable).quantize(Decimal("0.0001"))

    eligible = taxable > ZERO and ratio > threshold
    if eligible:
        reasons.append(
            f"Доставките с нулева ставка са {(ratio * 100).quantize(Decimal('0.1'))}% "
            f"от облагаемите — над изискуемите {(threshold * 100).quantize(Decimal('0.1'))}%."
        )
    elif taxable > ZERO:
        reasons.append(
            f"Доставките с нулева ставка са {(ratio * 100).quantize(Decimal('0.1'))}% — "
            f"под изискуемите {(threshold * 100).quantize(Decimal('0.1'))}%."
        )
    reasons.append("Авансовите плащания не участват в изчисляването.")

    return AcceleratedEligibility(
        eligible=eligible,
        zero_rate_amount=zero_rate.quantize(Decimal("0.01")),
        taxable_amount=taxable.quantize(Decimal("0.01")),
        ratio=ratio,
        threshold=threshold,
        period_from=start,
        period_to=end,
        reasons=reasons,
    )
