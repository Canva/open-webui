"""Conftest re-export for ``backend/tests/integration/``.

pytest collects parent ``conftest.py`` fixtures automatically when a
sub-directory contains its own ``conftest.py``, so this file is
intentionally minimal — it exists to make fixture provenance explicit
to readers who might otherwise wonder whether a separate engine /
client is being constructed for integration tests.
"""

from __future__ import annotations
