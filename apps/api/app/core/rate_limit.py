"""Ограничаване на честотата на опитите (brute force защита).

Реализацията е **плъзгащ прозорец в паметта на процеса** — без нови зависимости и
без Redis, какъвто проектът още няма. Това е достатъчно за текущия деплой
(един контейнер, `uvicorn --workers 2`); при повече процеси/машини всеки процес
брои отделно, тоест реалният праг се умножава по броя процеси. Когато се стигне
до хоризонтално мащабиране, се сменя само `SlidingWindowLimiter` с общо хранилище —
`RateLimitGuard` и зависимостите остават същите.

Ключът е комбинация от **IP + субект** (напр. имейл): само по IP наказва цял офис
зад един NAT, само по субект позволява обхождане на много акаунти от един атакуващ.

Използване в endpoint:

    LoginRateLimit = make_rate_limit_dependency("login", lambda: RateLimitRule(...))

    @router.post("/auth/login")
    def login(data: LoginRequest, guard: LoginRateLimit) -> Token:
        guard.check(data.email)          # вдига 429, ако прагът е изчерпан
        ...
        guard.register_failure(data.email)   # при неуспех
        guard.reset(data.email)              # при успех
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("app.security.rate_limit")

# Пазим паметта ограничена: периодично изхвърляме ключове без активни събития.
_CLEANUP_EVERY_SECONDS = 300


@dataclass(frozen=True)
class RateLimitRule:
    """Праг: най-много `max_attempts` събития в прозорец от `window_seconds`."""

    max_attempts: int
    window_seconds: int


class SlidingWindowLimiter:
    """Брои събития по ключ в плъзгащ прозорец. Безопасен за паралелни заявки."""

    def __init__(self, name: str, rule_provider: Callable[[], RateLimitRule]) -> None:
        self.name = name
        self._rule_provider = rule_provider
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    @property
    def rule(self) -> RateLimitRule:
        """Текущият праг (чете се от Settings при всяко обръщение)."""
        return self._rule_provider()

    # -- вътрешни ---------------------------------------------------------
    def _prune(self, key: str, now: float, window: float) -> deque[float]:
        events = self._events[key]
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def _cleanup(self, now: float, window: float) -> None:
        if now - self._last_cleanup < _CLEANUP_EVERY_SECONDS:
            return
        self._last_cleanup = now
        for key in list(self._events):
            self._prune(key, now, window)

    # -- публични ---------------------------------------------------------
    def retry_after(self, key: str) -> int | None:
        """Секунди до отпускане на ограничението, или None ако още има опити."""
        rule = self.rule
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, now, rule.window_seconds)
            if len(events) < rule.max_attempts:
                return None
            return max(1, math.ceil(events[0] + rule.window_seconds - now))

    def register(self, key: str) -> int:
        """Отчита едно събитие; връща броя събития в текущия прозорец."""
        rule = self.rule
        now = time.monotonic()
        with self._lock:
            self._cleanup(now, rule.window_seconds)
            events = self._prune(key, now, rule.window_seconds)
            events.append(now)
            self._events[key] = events
            return len(events)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# Регистър на всички лимитери — удобно за нулиране в тестове.
_LIMITERS: dict[str, SlidingWindowLimiter] = {}


def reset_all_limiters() -> None:
    """Нулира броячите на всички лимитери (използва се от тестовете)."""
    for limiter in _LIMITERS.values():
        limiter.clear()


def client_ip(request: Request) -> str:
    """IP на клиента; зад доверен reverse proxy — първият от X-Forwarded-For."""
    if settings.RATE_LIMIT_TRUST_PROXY_HEADER:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitGuard:
    """Обвързва лимитер с конкретната заявка (IP); субектът се подава от endpoint-а.

    Endpoint-ът контролира кога опитът е „неуспешен“ — затова броенето не е
    автоматично: `check()` преди работата, после `register_failure()` или `reset()`.
    """

    def __init__(self, limiter: SlidingWindowLimiter, ip: str) -> None:
        self._limiter = limiter
        self.ip = ip

    @property
    def enabled(self) -> bool:
        # Чете се при всяка заявка → изключваемо от тестове чрез settings.
        return settings.RATE_LIMIT_ENABLED

    def _key(self, subject: str) -> str:
        return f"{self._limiter.name}|{self.ip}|{subject.strip().lower()}"

    def check(self, subject: str) -> None:
        """Вдига 429 с `Retry-After`, ако прагът за IP+субект е изчерпан."""
        if not self.enabled:
            return
        retry_after = self._limiter.retry_after(self._key(subject))
        if retry_after is None:
            return
        minutes = max(1, math.ceil(retry_after / 60))
        logger.warning(
            "Блокиран опит (%s): subject=%s ip=%s retry_after=%ss",
            self._limiter.name,
            subject,
            self.ip,
            retry_after,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Твърде много неуспешни опити. Достъпът е временно ограничен — "
                f"опитайте отново след около {minutes} мин."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    def register_failure(self, subject: str, *, reason: str = "") -> None:
        """Отчита неуспешен опит и го логва за одит (без чувствителни данни)."""
        if not self.enabled:
            return
        attempts = self._limiter.register(self._key(subject))
        logger.warning(
            "Неуспешен опит (%s): subject=%s ip=%s опит=%d/%d%s",
            self._limiter.name,
            subject,
            self.ip,
            attempts,
            self._limiter.rule.max_attempts,
            f" причина={reason}" if reason else "",
        )

    def reset(self, subject: str) -> None:
        """Успешен изход → броячът за този IP+субект се изчиства."""
        self._limiter.reset(self._key(subject))


def make_rate_limit_dependency(
    name: str, rule_provider: Callable[[], RateLimitRule]
) -> Annotated[RateLimitGuard, Depends]:
    """Създава лимитер с име `name` и готова FastAPI зависимост към него."""
    limiter = SlidingWindowLimiter(name, rule_provider)
    _LIMITERS[name] = limiter

    def dependency(request: Request) -> RateLimitGuard:
        return RateLimitGuard(limiter, client_ip(request))

    return Annotated[RateLimitGuard, Depends(dependency)]
