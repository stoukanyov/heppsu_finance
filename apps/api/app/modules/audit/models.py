"""Одитен журнал — неизменим запис на действията (master prompt 14).

Append-only: няма endpoint-и за промяна или изтриване. Записва се от middleware при
всяко променящо API действие (POST/PUT/PATCH/DELETE).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class AuditLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # Могат да са None (напр. неуспешен вход преди издаване на токен).
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True, nullable=True)

    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
