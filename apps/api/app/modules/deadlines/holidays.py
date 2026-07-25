"""Календар на българските официални празници и работните дни.

Използва се за правилото „срок, паднал в неработен ден, се измества на следващия
работен ден“. Подвижните (Великденски) празници се изчисляват алгоритмично по
православната Пасха — без хардкод за отделни години.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

# ---------------------------------------------------------------- фиксирани
# Официални празници по чл. 154, ал. 1 от Кодекса на труда: (месец, ден, име).
# 1 ноември (Ден на народните будители) НЕ е тук — той е неприсъствен само за
# учебните заведения, не е официален почивен ден за всички.
FIXED_HOLIDAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Нова година"),
    (3, 3, "Ден на Освобождението на България"),
    (5, 1, "Ден на труда"),
    (5, 6, "Гергьовден, Ден на храбростта и Българската армия"),
    (5, 24, "Ден на светите братя Кирил и Методий, на българската азбука, просвета и култура"),
    (9, 6, "Ден на Съединението"),
    (9, 22, "Ден на Независимостта на България"),
    (12, 24, "Бъдни вечер"),
    (12, 25, "Рождество Христово"),
    (12, 26, "Рождество Христово"),
)


# ---------------------------------------------------------------- подвижни
def _julian_to_gregorian_offset(year: int) -> int:
    """Разлика между юлианския и григорианския календар в дни за дадена година.

    За 1900–2099 г. дава 13 дни, но е сметната по формула, а не хардкодната.
    """
    century = year // 100
    return century - century // 4 - 2


def orthodox_easter(year: int) -> dt.date:
    """Дата на православния Великден (Пасха) по григорианския календар.

    Алгоритъм на Мийус за юлианската Пасха:
        a = year mod 4, b = year mod 7, c = year mod 19
        d = (19c + 15) mod 30
        e = (2a + 4b − d + 34) mod 7
        месец = (d + e + 114) div 31, ден = (d + e + 114) mod 31 + 1
    Полученият юлиански ден се преобразува към григориански с отместването по-горе.
    """
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    julian_date = dt.date(year, month, day)
    return julian_date + dt.timedelta(days=_julian_to_gregorian_offset(year))


def easter_holidays(year: int) -> dict[dt.date, str]:
    """Великденските празници: Разпети петък, Велика събота, Великден и Велики понеделник."""
    easter = orthodox_easter(year)
    return {
        easter - dt.timedelta(days=2): "Разпети петък",
        easter - dt.timedelta(days=1): "Велика събота",
        easter: "Великден",
        easter + dt.timedelta(days=1): "Велики понеделник",
    }


# ------------------------------------------------------------------ календар
@lru_cache(maxsize=512)
def holiday_calendar(year: int) -> dict[dt.date, str]:
    """Всички неприсъствени празнични дни за годината (без обикновените уикенди).

    Прилага и правилото по чл. 154, ал. 2 КТ: когато официален празник (с изключение
    на Великденските) съвпадне със събота и/или неделя, първият (или първите два)
    работни дни след него също са неприсъствени.

    Резултатът се кешира — не го мутирайте.
    """
    calendar: dict[dt.date, str] = {}
    fixed = [(dt.date(year, month, day), name) for month, day, name in FIXED_HOLIDAYS]
    calendar.update(dict(fixed))
    calendar.update(easter_holidays(year))

    # Пренасяне на фиксираните празници, паднали в събота/неделя.
    for date_, name in sorted(fixed):
        if date_.weekday() < 5:  # 5 = събота, 6 = неделя
            continue
        candidate = date_ + dt.timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in calendar:
            candidate += dt.timedelta(days=1)
        calendar[candidate] = f"Почивен ден за {name}"
    return calendar


def holiday_name(date_: dt.date) -> str | None:
    """Име на официалния празник за датата или None, ако не е празник."""
    return holiday_calendar(date_.year).get(date_)


def is_holiday(date_: dt.date) -> bool:
    return date_ in holiday_calendar(date_.year)


def is_working_day(date_: dt.date) -> bool:
    """Работен ден = делник, който не е официален празник."""
    return date_.weekday() < 5 and not is_holiday(date_)


def next_working_day(date_: dt.date) -> dt.date:
    """Първият работен ден на или след подадената дата."""
    current = date_
    while not is_working_day(current):
        current += dt.timedelta(days=1)
    return current
