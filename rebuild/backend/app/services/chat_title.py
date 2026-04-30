"""Derive a sidebar title from the first user message.

A pure helper so the unit test (Phase 4a) is one fixture. Two call sites
in M2:

* ``POST /api/chats`` (Phase 2b) when the request body omits ``title``.
* The streaming pipeline (``app/services/chat_stream.py``, Phase 2c) on
  the first assistant turn for a chat that's still titled
  ``"New Chat"``.

Locked semantics (``rebuild/docs/plans/m2-conversations.md`` §
Deliverables, line 18): "≤ 60 chars, single line, stripped".

Implementation notes:

* The cap is on **characters**, not bytes — the legacy fork uses
  character count and we round-trip the same value to the sidebar UI,
  which renders glyph-by-glyph.
* The truncation marker is U+2026 HORIZONTAL ELLIPSIS, not three ASCII
  dots and not ``--``. One codepoint, one glyph, identical rendering on
  every system font.
* Empty input (or input that collapses to empty after the strip /
  whitespace-collapse) returns the project default ``"New Chat"`` so the
  sidebar never shows a blank row.
"""

from __future__ import annotations

import re

_WHITESPACE_RUN = re.compile(r"\s+")
_TITLE_CAP = 60
_ELLIPSIS = "\u2026"
_DEFAULT_TITLE = "New Chat"


def derive_title(first_user_message: str) -> str:
    collapsed = _WHITESPACE_RUN.sub(" ", first_user_message).strip()
    if not collapsed:
        return _DEFAULT_TITLE
    if len(collapsed) <= _TITLE_CAP:
        return collapsed
    return collapsed[:_TITLE_CAP] + _ELLIPSIS
