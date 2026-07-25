"""Отметки „подадено“ за срокове.

Единствената таблица на модула. Всичко останало се изчислява от календара —
тук се пази само това, което календарът не може да знае: че човек вече е
подал документа.

Ключът (`key`) е стабилният идентификатор от `DeadlineOut`, напр.
``vat-return:2026-07``. Проектиран е точно за това: не се променя между
извиквания и не зависи от преместването на датата заради празник.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DeadlineFiling(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "deadline_filings"
    __table_args__ = (
        # Един срок се отмята веднъж за компания. Ограничението е в базата, а не
        # само в кода: две едновременни заявки от два телефона иначе минават.
        UniqueConstraint("company_id", "key", name="uq_deadline_filing"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)

    filed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
