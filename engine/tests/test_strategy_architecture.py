"""Architecture guard: strategies decide, they never execute (AGENTS.md).

Strategy modules must never import ``trendbot.exchange`` or
``trendbot.execution`` — a strategy produces a decision; only the
execution layer touches adapters, and only after risk approval.

The check parses import statements via ``ast`` (docstrings that mention
the boundary do not count).
"""

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("trendbot.exchange", "trendbot.execution")


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_strategy_modules_never_import_exchange_or_execution():
    strategies_root = (
        Path(__file__).resolve().parents[1] / "src" / "trendbot" / "strategies"
    )
    assert strategies_root.is_dir()
    violations: list[str] = []
    for source in strategies_root.rglob("*.py"):
        for module in _imported_modules(source):
            for forbidden in FORBIDDEN_PREFIXES:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    violations.append(f"{source.name}: import {module}")
    assert violations == []
