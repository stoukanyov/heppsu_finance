"""Кое е „днес“ за фирмата, чието счетоводство водим.

`datetime.date.today()` връща деня по часовника на МАШИНАТА. Production сървърът
работи в UTC, а фирмите живеят в Europe/Sofia (UTC+2 зимата, UTC+3 лятото).
Между 00:00 и 03:00 софийско време двете дати са РАЗЛИЧНИ — и точно тогава
автоматичните задачи и нощните импорти работят най-често.

Каква щета пази този модул:

* Сторно, осчетоводено в 00:30 на 1 август, при `date.today()` получава дата
  31 юли и влиза в ЮЛСКИЯ ДДС дневник — период, чиято декларация вече може да е
  подадена в НАП. Корекцията после минава през коригираща декларация.
* Срок към НАП, изтекъл в края на 14-о число, в 01:00 на 15-о при `date.today()`
  още се брои за „днешен“, а не за просрочен — предупреждението не се показва.
* Дата на подаване (`submitted_at`), записана с ден назад, разминава нашия
  регистър с протокола на НАП.

Затова в кода на приложението НЕ се вика `dt.date.today()`. Правилото се пази от
линтера: `DTZ011` е включено в `ruff.toml`, а тестът
`tests/test_infra_guardrails.py::test_dtz011_niama_date_today_v_prilozhenieto`
пада, ако някой го върне.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings

# Резервна зона, ако настройката сочи към несъществуващо име. По-добре е грешна
# конфигурация да даде българското време, отколкото приложението да не тръгне:
# това е часова зона, не тайна.
_FALLBACK = "Europe/Sofia"


def business_timezone() -> ZoneInfo:
    """Часовата зона, в която фирмата брои дните."""
    try:
        return ZoneInfo(settings.BUSINESS_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(_FALLBACK)


def business_now() -> dt.datetime:
    """Текущият момент, изразен в часовата зона на фирмата (aware)."""
    return dt.datetime.now(tz=business_timezone())


def business_today() -> dt.date:
    """Днешната ДАТА според фирмата, не според часовника на сървъра."""
    return business_now().date()
