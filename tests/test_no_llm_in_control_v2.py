"""Static guard v2: no LLM / openai / urllib in the control loop.

This test extends ``tests/test_no_llm_in_control.py`` with two additional
checks tailored to the FEAT-004 services layer split:

* The scan covers ``core/control``, ``core/simulation``, ``core/safety``,
  ``core/optimizer`` and ``prediction/`` -- every package that
  participates in the supervisory control loop.
* In addition to banning import statements whose top-level package
  contains ``llm``, ``openai`` or ``urllib``, the test asserts that the
  literal substring ``LLM`` does NOT appear as a class or function name
  within those packages. The reporting client (``LLMClient`` under
  ``core/reporting``) IS allowed because it is not part of the control
  loop and so is not in the scan list.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS: tuple[Path, ...] = (
    REPO_ROOT / "core" / "control",
    REPO_ROOT / "core" / "simulation",
    REPO_ROOT / "core" / "safety",
    REPO_ROOT / "core" / "optimizer",
    REPO_ROOT / "prediction",
)

BANNED_IMPORT_TOKENS: tuple[str, ...] = ("llm", "openai", "urllib")
BANNED_NAME_SUBSTRINGS: tuple[str, ...] = ("LLM",)


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        if not d.is_dir():
            continue
        files.extend(sorted(d.rglob("*.py")))
    return files


def _import_top(name: str | None) -> str:
    if not name:
        return ""
    return name.split(".")[0].lower()


def test_no_llm_or_urllib_imports_in_control_packages() -> None:
    offenders: list[str] = []
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _import_top(alias.name) and any(
                        tok in alias.name.lower() for tok in BANNED_IMPORT_TOKENS
                    ):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}: import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module and any(
                    tok in module.lower() for tok in BANNED_IMPORT_TOKENS
                ):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: from {module} import ..."
                    )
    assert offenders == [], (
        "control-loop packages must not import llm/openai/urllib. "
        "Offending imports:\n  - " + "\n  - ".join(offenders)
    )


def test_no_llm_named_classes_or_functions_in_control_packages() -> None:
    """The literal substring 'LLM' must not appear as a class or function name."""
    offenders: list[str] = []
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                for token in BANNED_NAME_SUBSTRINGS:
                    if token in node.name:
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}: "
                            f"{type(node).__name__} {node.name}"
                        )
    assert offenders == [], (
        "control-loop packages must not declare names containing 'LLM'. "
        "Offending names:\n  - " + "\n  - ".join(offenders)
    )
