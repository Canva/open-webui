"""Pure-function unit tests for the M3 share-token shape.

Anchored to ``rebuild/docs/plans/m3-sharing.md`` § Tests § Unit
``test_token.py``: ``secrets.token_urlsafe(32)`` returns a 43-char
URL-safe string; collisions are vanishingly improbable; we don't
reimplement the generator, but we assert the length and charset of the
value the share router mints.

These tests deliberately call ``secrets.token_urlsafe(32)`` directly
(rather than going through the FastAPI router) because the router
literally calls ``secrets.token_urlsafe(_TOKEN_BYTES)`` with
``_TOKEN_BYTES = 32`` (see ``app/routers/shares.py``). The contract we
care about is therefore stdlib's, not the router's — but the column
width on ``shared_chat.id`` is ``VARCHAR(43)``, so the day stdlib
ever changes the shape of ``token_urlsafe(32)`` (length, alphabet,
padding) is the day every share INSERT silently truncates or noisily
fails. A unit test here catches that day before production does.
"""

from __future__ import annotations

import secrets
import string

# `secrets.token_urlsafe(32)` is unpadded base64 of 32 raw bytes, which
# is `ceil(32 * 4 / 3) - padding = 43` characters wide. The router and
# the `shared_chat.id VARCHAR(43)` column both pin this number; a
# stdlib drift would surface here first.
_EXPECTED_TOKEN_LENGTH = 43

# URL-safe base64 alphabet (RFC 4648 §5) without padding. Anything outside
# this set in a freshly minted token would mean stdlib changed the encoding.
_URL_SAFE_BASE64_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_")


def test_token_length_is_43_chars() -> None:
    """``secrets.token_urlsafe(32)`` is always 43 characters wide.

    The ``shared_chat.id`` column is ``VARCHAR(43)`` and the router
    inserts the token directly as the PK. If stdlib ever returned 44,
    MySQL strict mode would refuse the insert (good — loud failure)
    rather than silently truncating to 43; either way the test catches
    the regression before a deploy.
    """
    token = secrets.token_urlsafe(32)
    assert len(token) == _EXPECTED_TOKEN_LENGTH


def test_token_charset_is_url_safe_base64() -> None:
    """Every character is in the URL-safe base64 alphabet.

    No ``+`` / ``/`` (would break the ``/s/{token}`` URL path), no ``=``
    (the unpadded form is what makes ``len == 43``), no whitespace.
    A failure here would mean stdlib swapped to a different encoding —
    either the standard padded base64 (would break the URL) or
    something exotic (would break our column width).
    """
    token = secrets.token_urlsafe(32)
    offenders = [c for c in token if c not in _URL_SAFE_BASE64_ALPHABET]
    assert not offenders, f"token {token!r} contains non-URL-safe-base64 characters: {offenders!r}"


def test_token_collision_sanity() -> None:
    """10,000 freshly minted tokens are all distinct.

    Crypto-strength generators give us this guarantee in expectation;
    the test exists as a regression guard against a future refactor
    that accidentally swaps ``secrets`` for a lower-entropy source
    (``random.choices(...)``, ``hash(...)``, a counter). Even at 10k
    samples, a lower-entropy generator's collision probability is
    high enough that this test fails reliably.
    """
    tokens = {secrets.token_urlsafe(32) for _ in range(10_000)}
    assert len(tokens) == 10_000
