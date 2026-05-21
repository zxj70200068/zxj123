"""Static guard that the LLM-in-control path stays deleted.

This test parses every ``.py`` file under the control-loop subtrees of
``core/`` plus ``prediction/`` and asserts:

* No module imports ``urllib.request``, ``requests`` or ``openai``.
* No class name contains ``LLM``, ``BiLSTM`` or ``CloudAI`` (matching is
  case-sensitive but substring-based).
* The literal string ``campus-bilstm.cloud.local`` does not appear
  anywhere in the source text.

The legacy/ tree is excluded by virtue of not being under ``core/`` or
``prediction/``. The reporting subtree (``core/reporting``) is also
excluded: FEAT-004 reintroduces a reporting-only :class:`LLMClient`
there, which is allowed by design. ``tests/test_no_llm_in_control_v2.py``
provides the broader, FEAT-004-aware guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Scan every control-loop subtree of ``core/`` plus ``prediction/``. The
# reporting subtree (``core/reporting``) is intentionally **excluded**:
# FEAT-004 reintroduces a reporting-only :class:`LLMClient` there which is
# allowed by design. The same intent is enforced more comprehensively by
# ``tests/test_no_llm_in_control_v2.py``; this v1 test continues to lock
# the legacy banned-string regression in place for the control loop only.
SCAN_DIRS = (
    REPO_ROOT / "core" / "control",
    REPO_ROOT / "core" / "simulation",
    REPO_ROOT / "core" / "safety",
    REPO_ROOT / "core" / "optimizer",
    REPO_ROOT / "core" / "physics",
    REPO_ROOT / "core" / "prediction",
    REPO_ROOT / "prediction",
)

BANNED_IMPORTS: tuple[str, ...] = ("urllib.request", "requests", "openai")
BANNED_CLASS_SUBSTRINGS: tuple[str, ...] = ("LLM", "BiLSTM", "CloudAI")
BANNED_LITERALS: tuple[str, ...] = ("campus-bilstm.cloud.local",)


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            files.append(p)
    return files


def test_no_banned_imports() -> None:
    offenders: list[str] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - safety net
            pytest.fail(f"could not parse {path}: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in BANNED_IMPORTS:
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in BANNED_IMPORTS:
                    offenders.append(f"{path}: from {node.module} import ...")
    assert offenders == [], f"banned imports detected: {offenders}"


def test_no_banned_class_names() -> None:
    offenders: list[str] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - safety net
            pytest.fail(f"could not parse {path}: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for token in BANNED_CLASS_SUBSTRINGS:
                    if token in node.name:
                        offenders.append(f"{path}: class {node.name}")
    assert offenders == [], f"banned class names detected: {offenders}"


def test_no_banned_literal_strings() -> None:
    offenders: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        for lit in BANNED_LITERALS:
            if lit in text:
                offenders.append(f"{path}: contains {lit!r}")
    assert offenders == [], f"banned literal strings detected: {offenders}"
