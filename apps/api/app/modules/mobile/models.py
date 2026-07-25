"""Отчети за сривове от мобилния клиент.

Пазят се в базата, а не при трета страна: следата от срив във финансово
приложение съдържа имена на екрани, суми и идентификатори на документи, и
изнасянето ѝ навън е ненужен риск. Клиентът и без това чисти явните лични
данни преди изпращане — тук е втората линия.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class CrashReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "crash_reports"

    # И двете са nullable: срив може да настъпи преди вход или преди избор на компания.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    platform: Mapped[str] = mapped_column(String(20), nullable=False)      # ios | android
    app_version: Mapped[str] = mapped_column(String(40), nullable=False)
    build_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)          # FLUTTER | DART | ISOLATE
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Кога е станал сривът на устройството — може да е доста преди изпращането,
    # защото докладът чака следващо стартиране с мрежа.
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Хеш на нормализираното съобщение + началото на стека. Един и същ дефект от
    # хиляда устройства се вижда като един ред, а не като хиляда.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
