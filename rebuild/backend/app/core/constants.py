"""Project-wide constants. Not tunable per environment."""

STREAM_HEARTBEAT_SECONDS: int = 15
"""Heartbeat cadence for SSE (M1 chat streaming) and socket.io (M3 channels).

Single source of truth so the FE timeout-watchdog window stays consistent
across both transports. 15s is short enough that a stalled upstream is
detected before LB idle-cutoff, long enough that idle connections don't
generate measurable load.
"""

MAX_CHAT_HISTORY_BYTES: int = 1_048_576  # 1 MiB; enforced in M1 chat service
"""Cap on ``chat.history`` JSON payload. Larger and writes start contending on
the row lock; almost always a sign of a bug rather than a real conversation."""
