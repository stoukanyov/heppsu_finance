"""Identity & Access — глобална идентичност на потребителя.

Достъпът до конкретна компания се управлява през Membership (виж modules.companies).
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.companies.models import Membership


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Платформен супер-администратор (различен от роля в компания).
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"


class RevokeReason(str, enum.Enum):
    """Защо един refresh токен е спрял да важи — важно за одит и за поддръжка."""

    ROTATED = "ROTATED"            # нормална ротация: издаден е наследник
    LOGOUT = "LOGOUT"              # потребителят излезе
    EXPIRED = "EXPIRED"            # изтекъл при опит за ползване
    REUSE_DETECTED = "REUSE_DETECTED"  # преизползван токен → цялото семейство пада
    USER_REVOKED = "USER_REVOKED"  # ръчна отмяна (всички устройства)


class RefreshToken(UUIDMixin, TimestampMixin, Base):
    """Дълготраен refresh токен с ротация и откриване на преизползване.

    В базата се пази САМО SHA-256 хешът — изтичане на таблицата не дава на нападателя
    работещ токен. `created_at` (от TimestampMixin) е моментът на издаване.

    Всяка верига от ротации е едно **семейство** (`family_id` = id на първия токен от
    веригата, издаден при вход). `parent_id` сочи предшественика, тоест токена, чиято
    размяна е родила този. Двете заедно дават и бърза отмяна на цялото семейство, и
    възстановима история „кой от кого е произлязъл“.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Активните токени на един потребител се търсят при масова отмяна.
        Index("ix_refresh_tokens_user_family", "user_id", "family_id"),
    )

    # Хешът е и уникалният ключ за търсене при `/auth/refresh`.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Семейство: id на първия токен от веригата. За първия токен сочи към самия него.
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, nullable=False)
    # Предшественикът във веригата (None за първия токен от семейството).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Кога е разменен срещу нова двойка. Непразно + нов опит = преизползване (кражба).
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Диагностика: от кое устройство е издаден (полезно при разследване на кражба).
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RefreshToken {self.id} user={self.user_id} revoked={self.revoked_at}>"
