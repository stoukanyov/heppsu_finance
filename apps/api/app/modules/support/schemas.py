"""Pydantic схеми за докладването."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: Категориите на Control Center (`TicketIn.category`), без превод: дефект,
#: инцидент („нещо не работи сега“), предложение за подобрение.
Category = Literal["bug", "incident", "recommendation"]

#: Таваните са по-тесни от тези на Control Center (`title` 3..200, `body` 1..4000),
#: защото към текста се добавя контекст (екран, среда, номер на доклада) и
#: сглобеното тяло трябва да се побере в 4000. Виж `forwarder.build_ticket`.
SUBJECT_MIN = 3
SUBJECT_MAX = 200
MESSAGE_MAX = 3500
PAGE_MAX = 200


class SupportReportIn(BaseModel):
    category: Category
    subject: str = Field(min_length=SUBJECT_MIN, max_length=SUBJECT_MAX)
    message: str = Field(min_length=1, max_length=MESSAGE_MAX)
    page: str | None = Field(default=None, max_length=PAGE_MAX)

    @field_validator("subject", "message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """Само интервали не е тема. Иначе Control Center отказва с 422 чак при препращането."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("празно поле")
        return stripped

    @field_validator("subject")
    @classmethod
    def _subject_long_enough(cls, value: str) -> str:
        # След изрязването: „  a  “ минава min_length=3 преди него, но не и след.
        if len(value) < SUBJECT_MIN:
            raise ValueError("темата е твърде къса")
        return value


class SupportReportOut(BaseModel):
    """Отговорът казва истината за препращането, не само „прието“.

    `forwarded=False` значи: докладът е записан при нас и ще бъде препратен —
    клиентът НЕ бива да показва „изпратено до поддръжката“ като факт.
    """

    id: uuid.UUID
    forwarded: bool
    status: str               # pending | sent | rejected
    reference: str | None     # номерът на тикета в Control Center, ако вече е известен


class SupportConfigOut(BaseModel):
    configured: bool
