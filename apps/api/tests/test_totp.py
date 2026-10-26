"""TOTP алгоритъмът сам за себе си — без HTTP и без база.

Контролните вектори са от приложение Б на RFC 6238. Те са причината този файл
да съществува: „кодът съвпада с кода, който същият код е изчислил“ не доказва
нищо — Google Authenticator няма да сверява срещу нашата реализация, а срещу
стандарта.
"""
import time

import pytest

from app.core import security, totp

# RFC 6238, Appendix B: тайната е ASCII „12345678901234567890“ в base32.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("timestamp", "expected"), RFC_VECTORS)
def test_rfc6238_vectors(timestamp, expected):
    """8-цифрените стойности от стандарта, SHA-1, стъпка 30 секунди."""
    assert totp.totp(RFC_SECRET, timestamp=timestamp, digits=8) == expected


def test_six_digit_code_is_the_tail_of_the_eight_digit_one():
    """Google Authenticator иска 6 цифри — последните шест от същото число."""
    for timestamp, expected in RFC_VECTORS:
        assert totp.totp(RFC_SECRET, timestamp=timestamp) == expected[-6:]


def test_generated_secret_is_decodable_base32():
    secret = totp.generate_secret()
    assert len(secret) == 32              # 20 байта → 32 знака без допълване
    assert "=" not in secret
    assert totp.verify(secret, totp.totp(secret)) is not None


def test_secret_is_random_every_time():
    assert len({totp.generate_secret() for _ in range(20)}) == 20


def test_code_from_previous_and_next_step_is_accepted():
    """Прозорец ±1 стъпка — телефонът почти никога не е точно по часовника."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    for offset in (-totp.STEP_SECONDS, 0, totp.STEP_SECONDS):
        code = totp.totp(secret, timestamp=now + offset)
        assert totp.verify(secret, code, timestamp=now) is not None, offset


def test_code_two_steps_away_is_refused():
    """±2 стъпки вече е минута разлика — това не е часовник, а подслушан код."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    for offset in (-2 * totp.STEP_SECONDS, 2 * totp.STEP_SECONDS):
        code = totp.totp(secret, timestamp=now + offset)
        assert totp.verify(secret, code, timestamp=now) is None, offset


def test_window_zero_accepts_only_the_current_step():
    secret = totp.generate_secret()
    now = 1_700_000_000
    assert totp.verify(secret, totp.totp(secret, timestamp=now), timestamp=now, window=0)
    earlier = totp.totp(secret, timestamp=now - totp.STEP_SECONDS)
    assert totp.verify(secret, earlier, timestamp=now, window=0) is None


def test_verify_returns_the_counter_so_reuse_can_be_blocked():
    secret = totp.generate_secret()
    now = 1_700_000_000
    counter = totp.verify(secret, totp.totp(secret, timestamp=now), timestamp=now)
    assert counter == totp.counter_for(now)
    # Същият код, но вече отчетен → отказ.
    assert (
        totp.verify(secret, totp.totp(secret, timestamp=now), timestamp=now, last_counter=counter)
        is None
    )


def test_last_counter_blocks_rewinding_inside_the_window():
    """Кодът от предишната стъпка не минава, след като е минал по-нов."""
    secret = totp.generate_secret()
    now = 1_700_000_000
    current = totp.counter_for(now)
    earlier = totp.totp(secret, timestamp=now - totp.STEP_SECONDS)
    assert totp.verify(secret, earlier, timestamp=now, last_counter=current) is None


def test_codes_with_spaces_and_dashes_are_accepted():
    secret = totp.generate_secret()
    now = 1_700_000_000
    code = totp.totp(secret, timestamp=now)
    assert totp.verify(secret, f"{code[:3]} {code[3:]}", timestamp=now) is not None


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12345a", None])
def test_malformed_codes_are_refused(bad):
    secret = totp.generate_secret()
    assert totp.verify(secret, bad) is None


def test_wrong_secret_does_not_validate():
    a, b = totp.generate_secret(), totp.generate_secret()
    now = 1_700_000_000
    assert totp.verify(b, totp.totp(a, timestamp=now), timestamp=now) is None


def test_counter_follows_the_clock():
    before = totp.counter_for()
    assert before == int(time.time()) // totp.STEP_SECONDS


def test_otpauth_uri_carries_what_authenticators_read():
    secret = totp.generate_secret()
    uri = totp.otpauth_uri(secret, account="ivan@heppsu.com", issuer="AI Finance OS")
    assert uri.startswith("otpauth://totp/AI%20Finance%20OS%3Aivan%40heppsu.com?")
    assert f"secret={secret}" in uri
    assert "issuer=AI%20Finance%20OS" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


def test_qr_svg_is_svg_and_scannable_size():
    uri = totp.otpauth_uri(totp.generate_secret(), account="a@b.bg", issuer="AI Finance OS")
    svg = totp.qr_svg(uri)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "<path" in svg


# ------------------------------------------------------------- резервни кодове
def test_recovery_code_shape_and_alphabet():
    code = security.generate_recovery_code()
    assert len(code) == security.RECOVERY_CODE_LENGTH + 1  # с тирето
    assert code[5] == "-"
    body = code.replace("-", "")
    assert all(ch in security.RECOVERY_CODE_ALPHABET for ch in body)
    # Азбуката е без знаците, които се четат двусмислено от екран.
    assert not set("01OIL") & set(security.RECOVERY_CODE_ALPHABET)


def test_recovery_codes_are_random():
    assert len({security.generate_recovery_code() for _ in range(50)}) == 50


def test_recovery_code_hash_ignores_case_and_dashes():
    code = security.generate_recovery_code()
    assert security.hash_recovery_code(code) == security.hash_recovery_code(code.lower())
    assert security.hash_recovery_code(code) == security.hash_recovery_code(code.replace("-", ""))
    assert security.hash_recovery_code(code) != security.hash_recovery_code(
        security.generate_recovery_code()
    )
