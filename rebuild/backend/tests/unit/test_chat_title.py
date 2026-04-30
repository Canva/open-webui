"""Unit tests for :func:`app.services.chat_title.derive_title`.

Pure helper, two call sites in M2 (``POST /api/chats`` when ``title`` is
omitted; the streaming pipeline on the first assistant turn for an
untitled chat). One fixture per behaviour locked in plan
§ Deliverables, line 18 ("≤ 60 chars, single line, stripped").
"""

from __future__ import annotations

from app.services.chat_title import derive_title


def test_derive_title_strips_whitespace() -> None:
    """Leading/trailing whitespace stripped before any cap math runs."""
    assert derive_title("   hello world   ") == "hello world"


def test_derive_title_collapses_internal_whitespace_runs() -> None:
    """Multiple spaces / tabs / newlines collapse to a single space —
    the sidebar is one line, so newlines must not survive."""
    assert derive_title("hello\n\n\tworld\t  again") == "hello world again"


def test_derive_title_returns_new_chat_on_empty_input() -> None:
    """Empty / whitespace-only input returns the project default
    ``"New Chat"`` (the literal default on ``Chat.title``) so the
    sidebar never shows a blank row."""
    assert derive_title("") == "New Chat"
    assert derive_title("   ") == "New Chat"
    assert derive_title("\n\t\r ") == "New Chat"


def test_derive_title_truncates_at_60_chars_with_ellipsis() -> None:
    """61-char input → first 60 chars + U+2026 HORIZONTAL ELLIPSIS.

    Asserting the literal ``\\u2026`` codepoint (NOT three ASCII dots,
    NOT ``--``) is the locked plan choice in
    ``app/services/chat_title.py``'s docstring.
    """
    src = "a" * 61
    title = derive_title(src)
    assert title == "a" * 60 + "\u2026"
    # Defensive — the truncation marker must be a single codepoint.
    assert title.endswith("\u2026")
    assert "..." not in title
    assert "--" not in title


def test_derive_title_under_60_chars_returns_input_verbatim_after_strip() -> None:
    """Exactly 60 chars passes through without an ellipsis."""
    src = "a" * 60
    assert derive_title(src) == src
    # 59 chars too — defensive against an off-by-one on the ``<=`` cap.
    assert derive_title("b" * 59) == "b" * 59


def test_derive_title_handles_emoji() -> None:
    """``len()`` counts codepoints, so a 60-emoji input is exactly at
    the cap (no truncation) and a 61-emoji input gets the ellipsis.

    The legacy fork rendered emoji glyph-by-glyph; our helper preserves
    that contract by counting codepoints, not bytes (utf-8 encoding
    would over-count multi-byte glyphs).
    """
    sixty_emoji = "🎉" * 60
    assert derive_title(sixty_emoji) == sixty_emoji
    sixty_one_emoji = "🎉" * 61
    title = derive_title(sixty_one_emoji)
    assert title == "🎉" * 60 + "\u2026"
    assert len(title) == 61  # 60 emoji + 1 ellipsis codepoint
