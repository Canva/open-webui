"""Tests for ``app.core.ids.new_id``.

The contract from the m0 plan § ID and time helpers:

* RFC 9562 UUIDv7 — version nibble must be ``7``.
* Returned as ``str``, not ``UUID``.
* Lexicographic ordering across distinct millisecond buckets (the leading
  48 bits are an epoch-ms Unix timestamp).

Note: intra-millisecond monotonicity is *not* asserted. RFC 9562 makes the
per-ms counter optional (Method 1 of three counter-strategies), and the
``uuid7-standard`` package M0 pins uses fresh random bytes for the trailing
80 bits on every call. If a future regression requires intra-ms ordering,
swap the implementation to a counter-providing UUIDv7 (e.g. one that keeps
a thread-local counter for collisions inside a single ms) and reinstate the
old assertion at that point.
"""

from __future__ import annotations

import time
from uuid import UUID

from app.core.ids import new_id


def test_returns_str_not_uuid() -> None:
    value = new_id()
    assert isinstance(value, str)
    assert len(value) == 36  # canonical hyphenated form
    # Parses cleanly as a UUID.
    UUID(value)


def test_version_nibble_is_seven() -> None:
    """The 13th hex digit of a UUIDv7 is ``7``."""
    parsed = UUID(new_id())
    assert parsed.version == 7


def test_cross_bucket_ordering() -> None:
    """IDs generated in distinct millisecond buckets are lexicographically
    ordered by generation time.

    UUIDv7's leading 48 bits are an epoch-ms Unix timestamp, so an ID
    generated at time T2 > T1 has a lexicographically larger string
    representation than one generated at T1, provided T2 - T1 >= 1 ms.
    We assert that across a series of generations spaced by ``sleep(0.002)``.

    Note: intra-ms monotonicity is NOT guaranteed by ``uuid7-standard.create()``
    (which uses fresh random bytes per call). RFC 9562 makes the per-ms
    counter optional and our implementation declines it; if a future
    regression requires intra-ms ordering, swap to a counter-based UUIDv7
    implementation and reinstate that assertion.
    """
    samples: list[str] = []
    for _ in range(20):
        samples.append(new_id())
        time.sleep(0.002)  # 2 ms — comfortably into the next ms bucket

    assert samples == sorted(samples), (
        "UUIDv7 IDs from distinct millisecond buckets must be "
        "lexicographically ordered by generation time"
    )


def test_returned_ids_are_unique() -> None:
    """A trivial uniqueness check — collisions would indicate a broken RNG."""
    ids = {new_id() for _ in range(1_000)}
    assert len(ids) == 1_000


def test_timestamp_prefix_is_recent() -> None:
    """Sanity: the leading 48 bits decode to approximately ``now``.

    A wildly out-of-band timestamp would suggest a non-RFC-9562 backport
    (e.g. version-1/4 hybrid) silently slipped under the helper.
    """
    before_ms = int(time.time_ns() // 1_000_000)
    value = new_id()
    after_ms = int(time.time_ns() // 1_000_000)

    # First 48 bits == 12 hex chars (with one '-' between bytes 4 and 5).
    hex_ts = value.replace("-", "")[:12]
    decoded_ms = int(hex_ts, 16)
    # Allow 100ms slack on either side for clock jitter / GC pauses.
    assert before_ms - 100 <= decoded_ms <= after_ms + 100
