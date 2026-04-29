"""AST gate: every parameter under ``app/routers/`` that resolves a
``Depends(get_session)`` / ``Depends(get_user)`` must do so via the
``Annotated`` aliases ``DbSession`` / ``CurrentUser`` from
``app.core.deps`` — never as a bare default value.

Why an AST walk and not a regex grep: multi-line signatures, in-comment
matches, and ``Depends(get_session)`` referenced from the body of a
helper (allowed) all confound a regex. AST parsing reads the program the
way the interpreter does.

Scope: walks every ``.py`` under ``backend/app/routers/`` only.
``app/core/auth.py`` is intentionally exempt — it carries the
sanctioned circular-import workaround documented inline in that file
(``Annotated[AsyncSession, Depends(get_session)]`` to avoid importing
``app.core.deps``, which itself imports ``get_user``).
"""

from __future__ import annotations

import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTERS_DIR = HERE.parent / "app" / "routers"
BANNED = {"get_session", "get_user"}


def _is_bare_depends(default: ast.expr | None) -> str | None:
    """If ``default`` is a bare ``Depends(<name>)`` call, return the
    referenced function name (e.g. ``"get_user"``); else None.

    Handles both ``Depends(...)`` (function-call form, Depends imported
    directly) and ``fastapi.Depends(...)`` (attribute-access form).
    """
    if not isinstance(default, ast.Call):
        return None
    func = default.func
    if isinstance(func, ast.Name) and func.id == "Depends":
        if default.args and isinstance(default.args[0], ast.Name):
            return default.args[0].id
        return None
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "Depends"
        and default.args
        and isinstance(default.args[0], ast.Name)
    ):
        return default.args[0].id
    return None


def test_no_bare_depends_in_routers() -> None:
    assert ROUTERS_DIR.exists(), (
        f"expected app/routers/ at {ROUTERS_DIR}; AST gate cannot run " f"without it"
    )

    offenders: list[str] = []
    for py in sorted(ROUTERS_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                # Pair positional args with their (right-aligned) defaults.
                positional = node.args.args
                defaults = node.args.defaults
                offset = len(positional) - len(defaults)
                for idx, default in enumerate(defaults):
                    arg = positional[offset + idx]
                    name = _is_bare_depends(default)
                    if name in BANNED:
                        offenders.append(
                            f"{py.relative_to(ROUTERS_DIR.parent.parent.parent)}"
                            f":{node.lineno} `{arg.arg}: ... = Depends({name})`"
                        )
                # Keyword-only args carry their defaults in `kw_defaults`,
                # which is parallel to `kwonlyargs` (None where missing).
                for kwarg, kwdefault in zip(
                    node.args.kwonlyargs, node.args.kw_defaults, strict=False
                ):
                    if kwdefault is None:
                        continue
                    name = _is_bare_depends(kwdefault)
                    if name in BANNED:
                        offenders.append(
                            f"{py.relative_to(ROUTERS_DIR.parent.parent.parent)}"
                            f":{node.lineno} `{kwarg.arg}: ... = Depends({name})`"
                        )

    assert not offenders, (
        "Use Annotated aliases (CurrentUser, DbSession) in app/routers/. "
        "Offenders:\n  " + "\n  ".join(offenders)
    )
