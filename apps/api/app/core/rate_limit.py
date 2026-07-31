"""Ограничаване на опитите (brute force защита).

Броенето е в **базата** — таблицата `auth_throttle_events`. Това не е избор по
вкус: предишната реализация държеше плъзгащ прозорец в паметта на процеса и
затова прагът мълчаливо се умножаваше по броя uvicorn workers (при два процеса
конфигурираните 5 опита пропускаха 10), а всеки деплой нулираше броячите.
Общото хранилище маха и двете. Цената е три SELECT-а и един INSERT на неуспешен
вход — нищожна при обема на този endpoint.

**Три прага, не един.** Само `IP+акаунт` изглежда достатъчно, но не е:

* `pair` (IP + акаунт) — класическото налучкване на една парола от едно място;
* `subject` (акаунт, от всички IP-та) — същата атака, разпределена през ботнет
  или през ротиращи се IPv6 адреси. Без този брояч всеки нов адрес получава
  пълна нова квота;
* `ip` (IP, срещу всички акаунти) — *password spraying*: една вероятна парола
  срещу хиляди акаунти. При ключ, който включва акаунта, това не се брои
  никъде и минава напълно необезпокоявано.

Компромисът при `subject` е известен: който знае чужд имейл, може да го държи
заключен, като бърка нарочно. Затова прагът там е висок (по подразбиране 20 за
15 минути) — разпределена атака се нуждае от порядъци повече, а истински
потребител практически не стига дотам. Пълното махане на риска иска доверие към
устройството/IP-то, което е следваща стъпка, не тази.

Използване в endpoint:

    LoginThrottle = make_throttle_dependency("login", lambda: ThrottlePolicy(...))

    @router.post("/auth/login")
    def login(data: LoginRequest, guard: LoginThrottle) -> Token:
        guard.check(data.email)              # вдига 429, ако праг е изчерпан
        ...
        guard.register_failure(data.email)   # при неуспех
        guard.reset(data.email)              # при успех
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.security.models import AuthThrottleEvent

logger = logging.getLogger("app.security.rate_limit")

# Изхвърляме изтеклите редове периодично, а не при всяка заявка.
_CLEANUP_EVERY_SECONDS = 300
# Пазим ги малко след изтичането на прозореца — за разследване на инцидент.
_RETENTION_FACTOR = 4


@dataclass(frozen=True)
class RateLimitRule:
    """Праг: най-много `max_attempts` събития в прозорец от `window_seconds`."""

    max_attempts: int
    window_seconds: int


@dataclass(frozen=True)
class ThrottlePolicy:
    """Трите прага. `subject` и `ip` са по избор — има точки, където нямат смисъл.

    При отчетите за сривове например субектът е константа, тоест `pair` вече е
    „по IP" и отделен `ip` праг би бил същото нещо два пъти.
    """

    pair: RateLimitRule
    subject: RateLimitRule | None = None
    ip: RateLimitRule | None = None

    @property
    def longest_window(self) -> int:
        return max(
            rule.window_seconds for rule in (self.pair, self.subject, self.ip) if rule is not None
        )


class ThrottleStore:
    """Плъзгащ прозорец върху `auth_throttle_events`.

    Работи със **собствена** сесия, а не с тази на заявката: отчитането на
    неуспешен опит трябва да се запише дори когато endpoint-ът след това вдигне
    401 и транзакцията на заявката се върне назад.
    """

    def __init__(self, session_factory: Callable[[], object] = SessionLocal) -> None:
        self._session_factory = session_factory
        # Поотделно за всеки брояч — виж `_maybe_cleanup`.
        self._last_cleanup: dict[str, float] = {}

    # -- четене -----------------------------------------------------------
    def count_since(
        self,
        scope: str,
        cutoff: float,
        *,
        client_ip: str | None,
        subject: str | None,
        include_cleared: bool = False,
    ) -> tuple[int, float | None]:
        """Брой събития в прозореца и времето на най-старото от тях.

        `include_cleared` се подава само от прага по IP: успешният вход маркира
        редовете като изчистени за сметките по акаунт, но те продължават да тежат
        на този, който ги е направил.
        """
        conditions = [AuthThrottleEvent.scope == scope, AuthThrottleEvent.occurred_at > cutoff]
        if not include_cleared:
            conditions.append(AuthThrottleEvent.cleared_at.is_(None))
        if client_ip is not None:
            conditions.append(AuthThrottleEvent.client_ip == client_ip)
        if subject is not None:
            conditions.append(AuthThrottleEvent.subject == subject)

        with self._session_factory() as db:  # type: ignore[operator]
            count, oldest = db.execute(
                select(func.count(), func.min(AuthThrottleEvent.occurred_at)).where(*conditions)
            ).one()
        return int(count or 0), oldest

    # -- писане -----------------------------------------------------------
    def register(self, scope: str, client_ip: str, subject: str, retention: int) -> None:
        now = time.time()
        with self._session_factory() as db:  # type: ignore[operator]
            db.add(
                AuthThrottleEvent(
                    scope=scope, client_ip=client_ip, subject=subject, occurred_at=now
                )
            )
            db.commit()
            self._maybe_cleanup(db, scope, now, retention)

    def clear(self, scope: str, *, client_ip: str | None = None, subject: str | None = None) -> None:
        """Маркира редовете като изчистени — **не** ги трие.

        Триенето би свалило и брояча по IP: достатъчно е жертвите на едно
        пръскане да влязат нормално и нападателят получава пълна нова квота.
        Проверено — 5 събития по IP ставаха 0 след успешните входове на петте
        атакувани акаунта.
        """
        conditions = [AuthThrottleEvent.scope == scope, AuthThrottleEvent.cleared_at.is_(None)]
        if client_ip is not None:
            conditions.append(AuthThrottleEvent.client_ip == client_ip)
        if subject is not None:
            conditions.append(AuthThrottleEvent.subject == subject)
        with self._session_factory() as db:  # type: ignore[operator]
            db.execute(update(AuthThrottleEvent).where(*conditions).values(cleared_at=time.time()))
            db.commit()

    def clear_all(self) -> None:
        with self._session_factory() as db:  # type: ignore[operator]
            db.execute(delete(AuthThrottleEvent))
            db.commit()

    def _maybe_cleanup(self, db, scope: str, now: float, retention: int) -> None:  # noqa: ANN001
        """Изхвърля изтеклите редове — **само на този брояч**.

        Без условието по `scope` изтриването върви с давността на брояча, който
        случайно го е задействал: вход (прозорец 900 с) би трил отчети за сривове
        (прозорец 3600 с), докато те още се броят, и другият лимит тихо се
        обезсилва. Затова и моментът на последното чистене се пази поотделно.
        """
        if now - self._last_cleanup.get(scope, 0.0) < _CLEANUP_EVERY_SECONDS:
            return
        self._last_cleanup[scope] = now
        db.execute(
            delete(AuthThrottleEvent).where(
                AuthThrottleEvent.scope == scope,
                AuthThrottleEvent.occurred_at < now - retention,
            )
        )
        db.commit()


# Едно хранилище за целия процес — таблицата така или иначе е обща.
_STORE = ThrottleStore()

# Регистър на политиките по име — удобно за нулиране в тестове.
_POLICIES: dict[str, Callable[[], ThrottlePolicy]] = {}


def reset_all_limiters() -> None:
    """Нулира всички броячи (използва се от тестовете)."""
    _STORE.clear_all()


def client_ip(request: Request) -> str:
    """IP на клиента; зад доверен reverse proxy — адресът, който **proxy-то** е добавило.

    Тук беше истинска дупка: старият код връщаше *първия* адрес от
    `X-Forwarded-For`. nginx обаче слага `$proxy_add_x_forwarded_for`, което
    **добавя** реалния адрес към каквото клиентът е пратил — тоест първият
    елемент се задава от самия клиент. Проверено срещу production: 12 поредни
    неуспешни входа с подправен `X-Forwarded-For` минаха без нито едно 429,
    докато без header-а ограничението сработваше.

    Затова редът е: `X-Real-IP` (nginx го **презаписва** от `$remote_addr`,
    клиентът не може да го подправи), после последният елемент на
    `X-Forwarded-For`, после самата връзка.
    """
    if settings.RATE_LIMIT_TRUST_PROXY_HEADER:
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimitGuard:
    """Обвързва политика с конкретната заявка (IP); субектът се подава от endpoint-а.

    Endpoint-ът контролира кога опитът е „неуспешен" — затова броенето не е
    автоматично: `check()` преди работата, после `register_failure()` или
    `reset()`.
    """

    def __init__(self, name: str, policy_provider: Callable[[], ThrottlePolicy], ip: str) -> None:
        self.name = name
        self._policy_provider = policy_provider
        self.ip = ip

    @property
    def policy(self) -> ThrottlePolicy:
        # Чете се при всяка заявка → изключваемо от тестове чрез settings.
        return self._policy_provider()

    @property
    def enabled(self) -> bool:
        return settings.RATE_LIMIT_ENABLED

    def _normalize(self, subject: str) -> str:
        return subject.strip().lower()

    def _exceeded(self, subject: str) -> tuple[str, int] | None:
        """Кой праг е изчерпан и след колко секунди се отпуска (или None)."""
        policy = self.policy
        now = time.time()
        checks = (
            ("pair", policy.pair, self.ip, subject),
            ("subject", policy.subject, None, subject),
            ("ip", policy.ip, self.ip, None),
        )
        worst: tuple[str, int] | None = None
        for label, rule, ip_filter, subject_filter in checks:
            # `max_attempts <= 0` изключва прага. Нужно е там, където приложението
            # още не вижда истинския клиентски адрес: тогава всички заявки идват от
            # един и същ IP и прагът по IP не пази, а затваря входа за всички.
            if rule is None or rule.max_attempts <= 0:
                continue
            count, oldest = _STORE.count_since(
                self.name,
                now - rule.window_seconds,
                client_ip=ip_filter,
                subject=subject_filter,
                # Само прагът по IP брои и вече изчистените редове — успешният вход
                # на жертвата не бива да връща квотата на нападателя.
                include_cleared=(label == "ip"),
            )
            if count < rule.max_attempts or oldest is None:
                continue
            retry_after = max(1, math.ceil(oldest + rule.window_seconds - now))
            # Показваме най-дългото изчакване — иначе клиентът се връща рано и
            # пак получава 429.
            if worst is None or retry_after > worst[1]:
                worst = (label, retry_after)
        return worst

    def check(self, subject: str, *, detail: str | None = None) -> None:
        """Вдига 429 с `Retry-After`, ако някой от праговете е изчерпан.

        `detail` позволява различен текст там, където ограничението не пази от
        познаване на парола (напр. приемане на отчети за сривове) — иначе
        клиентът получава съобщение за „неуспешни опити", каквито няма.
        """
        if not self.enabled:
            return
        exceeded = self._exceeded(self._normalize(subject))
        if exceeded is None:
            return
        label, retry_after = exceeded
        minutes = max(1, math.ceil(retry_after / 60))
        logger.warning(
            "Блокиран опит (%s, праг=%s): subject=%s ip=%s retry_after=%ss",
            self.name,
            label,
            subject,
            self.ip,
            retry_after,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail
            or (
                "Твърде много неуспешни опити. Достъпът е временно ограничен — "
                f"опитайте отново след около {minutes} мин."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    def register_event(self, subject: str) -> None:
        """Отчита едно събитие, без да го нарича „неуспех".

        За крайни точки, при които всяко обръщение се брои (не само сгрешените).
        """
        if not self.enabled:
            return
        _STORE.register(
            self.name,
            self.ip,
            self._normalize(subject),
            self.policy.longest_window * _RETENTION_FACTOR,
        )

    def register_failure(self, subject: str, *, reason: str = "") -> None:
        """Отчита неуспешен опит и го логва за одит (без чувствителни данни)."""
        if not self.enabled:
            return
        self.register_event(subject)
        logger.warning(
            "Неуспешен опит (%s): subject=%s ip=%s%s",
            self.name,
            subject,
            self.ip,
            f" причина={reason}" if reason else "",
        )

    def reset(self, subject: str) -> None:
        """Успешен изход → броячите за акаунта се изчистват.

        Чисти се и `pair`, и `subject`: успешният вход доказва, че това не е
        налучкване, и не бива потребител да остане заключен от чужди опити.
        Броячът по **IP** нарочно остава — иначе е достатъчно нападателят да има
        един собствен акаунт, за да си нулира квотата за spraying след всеки залп.

        Затова редовете се маркират, а не се трият: те са едни и същи за трите
        прага и `DELETE` сваляше и сметката по IP. Пръскане срещу пет акаунта се
        нулираше само защото петте жертви после са влезли нормално.
        """
        _STORE.clear(self.name, subject=self._normalize(subject))


def make_throttle_dependency(
    name: str, policy_provider: Callable[[], ThrottlePolicy]
) -> Annotated[RateLimitGuard, Depends]:
    """Създава брояч с име `name` и готова FastAPI зависимост към него."""
    _POLICIES[name] = policy_provider

    def dependency(request: Request) -> RateLimitGuard:
        return RateLimitGuard(name, policy_provider, client_ip(request))

    return Annotated[RateLimitGuard, Depends(dependency)]


def make_rate_limit_dependency(
    name: str, rule_provider: Callable[[], RateLimitRule]
) -> Annotated[RateLimitGuard, Depends]:
    """Вариант с един праг (IP + субект) — за точки, където другите два нямат смисъл."""
    return make_throttle_dependency(name, lambda: ThrottlePolicy(pair=rule_provider()))
