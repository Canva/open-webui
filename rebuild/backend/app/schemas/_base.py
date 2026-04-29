"""Project-wide Pydantic base. Every request/response schema in
``app/schemas/`` inherits from :class:`StrictModel`, never from ``BaseModel``
directly. See ``rebuild/plans/m0-foundations.md`` § Pydantic conventions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Project-wide Pydantic base.

    - extra="forbid": typo'd request fields (`{"acrhived": true}`) become a 422
      instead of being silently ignored. Closes the most common shape-drift bug
      in JSON-body APIs.
    - str_strip_whitespace=True: incoming strings have leading/trailing
      whitespace stripped at validation time, so the DB never stores
      `"  hello  "`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
