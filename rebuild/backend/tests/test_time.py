"""Tests for ``app.core.time.now_ms``."""

from __future__ import annotations

import pytest
from app.core import time as time_module
from app.core.time import now_ms


def test_type_is_int() -> None:
    assert isinstance(now_ms(), int)


def test_now_ms_matches_frozen_time_ns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkey-patch ``time.time_ns`` to a known value; assert the helper
    returns ``time_ns // 1_000_000``.

    Patches the *bound* reference inside ``app.core.time`` (it imports the
    ``time`` module, then references ``time.time_ns``). So patching
    ``app.core.time.time.time_ns`` is the right surface.
    """
    frozen_ns = 1_704_067_200_123_456_789  # 2024-01-01 00:00:00.123456789 UTC
    monkeypatch.setattr(time_module.time, "time_ns", lambda: frozen_ns)

    assert now_ms() == frozen_ns // 1_000_000
    assert now_ms() == 1_704_067_200_123


def test_resolution_is_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-ms changes to ``time_ns`` must not move ``now_ms``."""
    base_ns = 1_704_067_200_000_000_000
    for offset in (0, 100, 999_999):
        monkeypatch.setattr(time_module.time, "time_ns", lambda offset=offset: base_ns + offset)
        assert now_ms() == base_ns // 1_000_000
