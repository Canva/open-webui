"""Unit tests for the rebuild backend.

Sub-suite for tests that exercise pure functions and small isolated
classes WITHOUT touching the DB / HTTP / Redis / agent gateway.
Re-uses the parent ``tests/conftest.py`` fixtures via pytest's automatic
conftest collection; no per-directory conftest is needed.
"""
