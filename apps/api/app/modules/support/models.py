"""Доклади от потребителите — първо в нашата база, после към Control Center.

Редът е нарочен: докладът е приет, когато е записан тук, не когато Control
Center отговори. Ако Control Center е недостъпен, върне 5xx или 429, редът
остава `pending` и фоновият цикъл (`forwarder.py`) опитва пак. Докладът не се
губи, защото мрежата е паднала точно когато човекът е решил да ни пише.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

#: Чака препращане (още не е опитано, или опитът не е стигнал до Control Center).
STATUS_PENDING = "pending"
#: Control Center го прие и върна номер на тикет. Никога не се праща повторно.
STATUS_SENT = "sent"
#: Control Center отхвърли самото съдържание (400/422) — повторение няма да помогне.
#: Докладът остава в базата и се вижда; човек решава какво да прави с него.
STATUS_REJECTED = "rejected"


class SupportReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "support_reports"

    # Nullable и SET NULL: изтриването на акаунт или дружество не бива да трие
    # следата, че е имало сигнал (и не бива да спира изтриването).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Речникът на Control Center (bug | incident | recommendation) — един и същ
    # от формата до тикета, без превод по пътя, който да се обърка.
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Екранът, от който е докладвано (напр. „vat“) — помага при триажа.
    page: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Адресът на подателя така, както го е видял сървърът в момента на доклада.
    # Пази се, защото препращането може да стане по-късно от фоновия цикъл —
    # тогава заявката отдавна я няма, а Control Center брои квотата си по него
    # (`X-Submitter-IP`).
    submitter_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    forward_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING
    )
    # Номерът от Control Center (T-000123). Попълнен ⇔ статусът е `sent`.
    reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Кога е следващият опит. NULL при нов доклад = „веднага, щом е настроено“.
    next_attempt_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Заемане на реда от един процес. uvicorn върви с няколко работника и всеки
    # има свой фонов цикъл — без заемането два процеса пращат един доклад и
    # Control Center отваря два тикета.
    claimed_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Фоновият цикъл пита точно това: чакащите, чийто ред е дошъл.
        Index("ix_support_reports_due", "forward_status", "next_attempt_at"),
    )
