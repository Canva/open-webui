"""Smoke imports for ``app.core.constants``.

Both constants are referenced by name from M1 (``chat_stream.py``,
``chat_service.py``) and M3 (``realtime/sio.py``). Pinning the values
here means a typo in either later milestone fails fast in M0's unit
suite.
"""

from __future__ import annotations


def test_stream_heartbeat_seconds_value() -> None:
    from app.core.constants import STREAM_HEARTBEAT_SECONDS

    assert STREAM_HEARTBEAT_SECONDS == 15
    assert isinstance(STREAM_HEARTBEAT_SECONDS, int)


def test_max_chat_history_bytes_value() -> None:
    from app.core.constants import MAX_CHAT_HISTORY_BYTES

    assert MAX_CHAT_HISTORY_BYTES == 1_048_576
    assert isinstance(MAX_CHAT_HISTORY_BYTES, int)
