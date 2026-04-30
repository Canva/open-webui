"""Integration tests for the rebuild backend.

Sub-suite for tests that wire the full FastAPI app + a real DB session
together AND assert cross-cutting invariants (e.g. "theming touches no
DB tables", "the realtime fan-out hits no SQL", ...).

Re-uses the parent ``tests/conftest.py`` fixtures via pytest's automatic
conftest collection; nothing special needed in this directory.
"""
