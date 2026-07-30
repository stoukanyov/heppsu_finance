"""Хранилище на неуспешните опити — общо за всички процеси и машини."""
from __future__ import annotations

from sqlalchemy import Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class AuthThrottleEvent(UUIDMixin, Base):
    """Един отчетен неуспешен опит (вход, отчет за срив, каквото го брои).

    Редът е нарочно плосък — без външни ключове към `users`: опитите срещу
    несъществуващ имейл трябва да се броят точно колкото и тези срещу истински,
    иначе самото ограничение би издавало кои акаунти съществуват.

    `occurred_at` е **unix време като число**, а не `DateTime`. SQLite връща
    datetime без часова зона, PostgreSQL — с; сравнението „в рамките на
    прозореца" тогава изисква различен код за двете бази и грешката излиза чак
    в production (виж същия капан в `identity.service._aware`). Числото се
    сравнява еднакво навсякъде.
    """

    __tablename__ = "auth_throttle_events"

    #: Кой брояч — "login", "crash-report", …
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    #: IP на клиента така, както го е видял сървърът (виж `rate_limit.client_ip`).
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Срещу какво е бил опитът — имейл, идентификатор на устройство и т.н.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[float] = mapped_column(Float, nullable=False)
    #: Кога успешен вход е спрял този ред да тежи на **сметките по акаунт**.
    #:
    #: Успешният вход трябва да освободи потребителя, но не бива да връща на
    #: нападателя квотата му по IP. Затова редът не се трие: маркира се. Праговете
    #: `pair` и `subject` броят само немаркирани редове, а прагът по IP брои всички —
    #: иначе е достатъчно жертвите да влязат нормално, за да се нулира брояча на
    #: този, който ги е атакувал.
    cleared_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    # По един индекс за всеки от трите прага — иначе всяка проверка при вход
    # чете цялата таблица.
    __table_args__ = (
        Index("ix_auth_throttle_pair", "scope", "client_ip", "subject", "occurred_at"),
        Index("ix_auth_throttle_subject", "scope", "subject", "occurred_at"),
        Index("ix_auth_throttle_ip", "scope", "client_ip", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthThrottleEvent {self.scope} {self.client_ip} {self.subject}>"
