"""TOTP (RFC 6238) — втори фактор при вход, съвместим с Google Authenticator.

Собствена реализация, не библиотека: алгоритъмът е HMAC-SHA1 върху брояча на
30-секундните стъпки и се побира в няколко реда, а всяка външна зависимост в
пътя на входа е повърхност за атака и още нещо за обновяване. Правилността е
проверена срещу контролните вектори от RFC 6238 (виж tests/test_totp.py).

Параметрите са тези, които Google Authenticator приема **без** да му се казват:
SHA-1, 6 цифри, стъпка 30 секунди. Други стойности се описват в `otpauth://`
URI-то, но приложенията ги четат избирателно — затова не ги пипаме.

Защита срещу повторно ползване: `verify` връща **брояча**, а не True/False.
Извикващият пази последния приет брояч и отказва всичко, което не е строго
над него. Така един и същ код не минава два пъти, нито се „превърта“ назад в
рамките на прозореца за часовата разлика.
"""
from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
from urllib.parse import quote

#: Дължина на тайната. RFC 4226 иска поне 128 бита; 160 е размерът на изхода на
#: SHA-1 и е препоръчаната стойност. 20 байта → 32 знака base32.
SECRET_BYTES = 20
#: Стъпка в секунди — стойността по подразбиране на всички автентикатори.
STEP_SECONDS = 30
#: Брой цифри в кода.
DIGITS = 6
#: Колко стъпки назад и напред се приемат (часовата разлика на телефона).
#: ±1 стъпка = до 30 секунди разминаване, тоест общо до 90 секунди прозорец.
DEFAULT_WINDOW = 1

_BASE32_PAD = "="


def generate_secret() -> str:
    """Нова тайна в base32 без допълване — такава, каквато се чете от QR кода."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip(_BASE32_PAD)


def _decode_secret(secret: str) -> bytes:
    """base32 → байтове. Допълването се възстановява, регистърът не е от значение."""
    cleaned = secret.strip().replace(" ", "").upper()
    padding = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + _BASE32_PAD * padding, casefold=True)


def normalize_code(code: str) -> str:
    """Маха интервалите и тиретата, които автентикаторите показват за четимост."""
    return "".join(ch for ch in (code or "") if ch.isdigit())


def is_totp_code(code: str) -> bool:
    """Дали входът е TOTP код (шест цифри), а не резервен код.

    Разпознаването НЕ може да е „колко цифри има в низа“: азбуката на резервните
    кодове съдържа и цифри (`23456789ABCDEFGHJKMNPQRSTUVWXYZ`), тоест резервен
    код с точно шест цифри и четири букви — около **1 на 53** — се броеше за
    TOTP код, минаваше по TOTP проверката и даваше 401. Човек с изгубен телефон
    оставаше заключен точно с този код, а тестът за резервните кодове не минаваше
    веднъж на всеки ~15 пускания.

    Правилото е по форма, не по съдържание: махат се разделителите, които
    автентикаторите показват за четимост, и остатъкът е TOTP код само ако е
    точно шест знака и всички са цифри. Резервният код е десет знака, тоест
    двете форми не се застъпват.
    """
    cleaned = "".join(ch for ch in (code or "") if not ch.isspace() and ch != "-")
    return len(cleaned) == DIGITS and cleaned.isdigit()


def counter_for(timestamp: float | None = None) -> int:
    """Брояч на 30-секундната стъпка за даден момент (по подразбиране — сега)."""
    return int((time.time() if timestamp is None else timestamp) // STEP_SECONDS)


def hotp(secret: str, counter: int, *, digits: int = DIGITS, digest: str = "sha1") -> str:
    """HOTP по RFC 4226 — кодът за конкретен брояч."""
    mac = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), digest).digest()
    # Динамично отрязване: долните 4 бита на последния байт дават отместването.
    offset = mac[-1] & 0x0F
    (chunk,) = struct.unpack(">I", mac[offset : offset + 4])
    return str((chunk & 0x7FFFFFFF) % (10**digits)).zfill(digits)


def totp(secret: str, *, timestamp: float | None = None, digits: int = DIGITS) -> str:
    """Кодът за текущата (или подадената) стъпка — ползва се и от тестовете."""
    return hotp(secret, counter_for(timestamp), digits=digits)


def verify(
    secret: str,
    code: str,
    *,
    timestamp: float | None = None,
    window: int = DEFAULT_WINDOW,
    last_counter: int | None = None,
) -> int | None:
    """Проверява код и връща приетия брояч, или None.

    `last_counter` е последният вече използван брояч за този потребител: всичко
    до него включително се отказва, дори да е математически вярно. Без това един
    подслушан код важи до 90 секунди и може да бъде употребен повторно.
    """
    digits = len(normalize_code(code))
    if digits != DIGITS:
        return None
    candidate = normalize_code(code)
    try:
        _decode_secret(secret)
    except (ValueError, TypeError):
        return None

    current = counter_for(timestamp)
    accepted: int | None = None
    # Обхождат се всички стъпки от прозореца без ранно излизане — иначе времето
    # на отговора издава колко близо е бил кодът.
    for counter in range(current - window, current + window + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(hotp(secret, counter), candidate) and accepted is None:
            accepted = counter
    return accepted


def otpauth_uri(secret: str, *, account: str, issuer: str) -> str:
    """`otpauth://` URI за QR кода.

    Издателят стои и в етикета (`issuer:account`), и като параметър — старите
    версии на Google Authenticator четат само етикета, новите само параметъра.
    """
    label = quote(f"{issuer}:{account}", safe="")
    params = "&".join(
        [
            f"secret={quote(secret, safe='')}",
            f"issuer={quote(issuer, safe='')}",
            "algorithm=SHA1",
            f"digits={DIGITS}",
            f"period={STEP_SECONDS}",
        ]
    )
    return f"otpauth://totp/{label}?{params}"


def qr_svg(uri: str, *, scale: int = 5, dark: str = "#101418", light: str = "#ffffff") -> str:
    """QR код като вграден SVG (без външни файлове и без растерни зависимости).

    `segno` е чист Python без собствени зависимости — алтернативата `qrcode`
    води Pillow, който е ненужна тежест в образа само за една картинка.
    """
    import segno

    return segno.make(uri, error="m").svg_inline(scale=scale, border=2, dark=dark, light=light)
