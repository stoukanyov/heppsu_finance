"""Счетоводна кантора — работа с много клиентски дружества наведнъж.

**Решение D-013: няма нов субект „кантора".** Кантората вече съществува в данните —
това е наборът от компании, в които даден потребител е член (`Membership`). Въвеждането
на отделна таблица `Firm` би дублирало понятие и би създало втори, конкурентен път за
контрол на достъпа. Затова:

* „моите клиенти“ = компаниите, в които имам членство;
* „член на кантората вижда само възложените му клиенти“ се получава наготово от
  съществуващия tenant скоуп — без нито един нов ред логика за достъп;
* „възлагане на клиент“ = добавяне на членство, което вече има екран („Екип“).

Единственото, което липсва в данните, е **задачата** — работа по конкретен клиент,
възложена на човек, със срок. Тя е тук.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class TaskStatus(str, enum.Enum):
    OPEN = "OPEN"                # за правене
    IN_PROGRESS = "IN_PROGRESS"  # в процес
    DONE = "DONE"                # готова
    CANCELLED = "CANCELLED"      # отпаднала


class FirmTask(UUIDMixin, TimestampMixin, Base):
    """Задача по клиент — възложена на човек, със срок.

    `deadline_key` свързва задачата със срок от модула `deadlines` (напр.
    `vat-return:2026-07`). Сроковете се изчисляват, не се пазят — затова задачата пази
    ключа, а не външен ключ. Така една задача не се дублира при всяко зареждане на екрана.
    """

    __tablename__ = "firm_tasks"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, length=20), default=TaskStatus.OPEN, nullable=False
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deadline_key: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
