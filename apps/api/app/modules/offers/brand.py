"""Логото на документа — кое дружество има право да го носи.

Системата е многофирмена: кантора води офертите на чужди дружества. Логото на
ХЕПСУ върху оферта на клиентско дружество е чужд знак върху чужд документ, затова
се рисува само когато издателят е самото дружество, на което логото принадлежи.
За останалите остава името със сериф — както изглежда и празна бланка.

Дружеството се разпознава по ЕИК: името се сменя, ЕИК-ът — не.
"""
from __future__ import annotations

from pathlib import Path

#: ХЕПСУ КОНСУЛТИНГ ЕООД по Търговския регистър.
BRAND_EIK = "208418861"

#: Пътят към файла в репото; `app/web/logo.png` е същият файл за екрана.
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"


def logo_for(company) -> Path | None:
    """Пътят до логото за това дружество или `None`, ако няма право на него."""
    eik = (getattr(company, "eik", "") or "").strip()
    if eik != BRAND_EIK or not LOGO_PATH.is_file():
        return None
    return LOGO_PATH


def has_logo(company) -> bool:
    return logo_for(company) is not None
