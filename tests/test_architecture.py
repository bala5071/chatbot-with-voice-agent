"""Structural rules, checked on the source's syntax tree."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "voice_agent"
SCANNED = sorted([*SRC.rglob("*.py"), *(ROOT / "scripts").glob("*.py")])

# Modules that may touch the outside world; every other module is logic.
ENGINE_MODULES = {"engines/faster_whisper.py", "engines/piper.py"}
WIRING = {"cli.py"}
NETWORK = {"gateway_client.py"}
HEAVY = ("faster_whisper", "piper", "httpx", "voice_agent.engines", "ctranslate2", "onnxruntime")


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if path.is_relative_to(SRC) else path.name


def imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def reveal_calls(tree: ast.AST) -> list[str]:
    """The enclosing function of every ``.reveal()`` call."""
    calls: list[str] = []

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reveal"
        ):
            calls.append(function)
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return calls


def test_reveal_is_called_only_where_the_header_is_built() -> None:
    found = {
        rel(path): calls
        for path in SCANNED
        if (calls := reveal_calls(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert found == {"gateway_client.py": ["_auth_headers"]}


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: rel(p))
def test_logic_modules_do_not_import_engines_or_the_network(path: Path) -> None:
    name = rel(path)
    if name in ENGINE_MODULES | WIRING | NETWORK:
        return
    heavy = {
        module
        for module in imports(ast.parse(path.read_text(encoding="utf-8")))
        if module.split(".")[0] in {h.split(".")[0] for h in HEAVY}
        and any(module == h or module.startswith(h + ".") for h in HEAVY)
    }
    assert heavy == set()


def test_only_the_clock_imports_time() -> None:
    users = {
        rel(path)
        for path in SRC.rglob("*.py")
        if {"time", "datetime"} & imports(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert users == {"clock.py"}


def test_piper_is_imported_only_by_its_engine() -> None:
    users = {
        rel(path)
        for path in [*SCANNED, *(ROOT / "tests").rglob("*.py")]
        if any(
            m == "piper" or m.startswith("piper.")
            for m in imports(ast.parse(path.read_text(encoding="utf-8")))
        )
    }
    assert users == {"engines/piper.py"}
