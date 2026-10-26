"""Identity & Access — глобална идентичност на потребителя.

Достъпът до конкретна компания се управлява през Membership (виж modules.companies).
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Uuid
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


class UserTotp(UUIDMixin, TimestampMixin, Base):
    """Втори фактор (TOTP) на един потребител — един ред, най-много.

    2FA е на **потребителя**, не на дружеството: една сметка участва в няколко
    дружества с различни роли, а телефонът в джоба е един.

    `confirmed_at` е разликата между „започнато включване“ и „включено“. Редът се
    създава в момента, в който покажем QR кода, но дотогава тайната не пази нищо:
    без потвърден код входът продължава да минава само с парола. Иначе потребител,
    който е затворил екрана по средата, остава заключен извън акаунта си.

    Тайната се пази в чист вид (base32). Това не е пропуск, а необходимост:
    кодът се изчислява с HMAC върху самата тайна, тоест тя трябва да е
    възстановима — еднопосочен хеш като при паролата е невъзможен. Редът е
    толкова чувствителен, колкото и `users.hashed_password`, и дава **само
    втория** фактор: с открадната база нападателят още няма паролата.
    """

    __tablename__ = "user_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    #: Споделената тайна в base32 — същият низ, който стои в QR кода.
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Кога потребителят е доказал, че автентикаторът му работи. None = само започнато.
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Последният приет 30-секунден брояч. Приема се само строго по-голям —
    #: така един и същ код не минава два пъти, нито се „превърта“ назад в
    #: рамките на прозореца за часовата разлика. BigInteger: броячът е unix
    #: време / 30 и ще надхвърли 2^31 през 2038 г., а Integer на PostgreSQL е
    #: точно 32-битов.
    last_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserTotp user={self.user_id} confirmed={self.confirmed_at is not None}>"


class TotpRecoveryCode(UUIDMixin, TimestampMixin, Base):
    """Еднократен резервен код — вход без телефона.

    В базата е само SHA-256 хешът, както при refresh токените: кодът е случаен
    (50 бита), не е избран от човек, и bcrypt би направил проверката скъпа без
    да добави защита. Виж `core.security.hash_recovery_code`.

    Кодовете не се трият при употреба: `used_at` остава, за да се вижда, че
    някой е влизал с резервен код — това е сигнал за изгубено устройство.
    """

    __tablename__ = "totp_recovery_codes"
    __table_args__ = (
        # Проверката при вход търси точно по тази двойка.
        Index("ix_totp_recovery_user_hash", "user_id", "code_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TotpRecoveryCode user={self.user_id} used={self.used_at is not None}>"
