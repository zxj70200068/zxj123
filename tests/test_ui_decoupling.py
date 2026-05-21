"""Static guard: ui/ may only import from services.*, data.configs.*, utils.*.

The legacy ``MainPlatformGUI`` constructed engine internals (WhiteBoxEngine,
AIReportAgent, SimulationRunner, HistoryLogger) directly. After FEAT-004,
the UI layer talks to the new services/ facade exclusively. This test
parses every ``.py`` file under ``ui/`` with :mod:`ast` and asserts that
no module imports anything whose top-level package is ``core``,
``prediction``, ``train`` or ``models``.

Allowed cross-package imports from ``ui/``:

* ``services.*`` -- the simulation, control, reporting facade
* ``data.configs.*`` -- default scenario / strategy registries / LLM presets
* ``utils.*`` -- logging and path helpers

Stdlib + tkinter + matplotlib (and any other third-party frontend
package) are not flagged.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ROOT = REPO_ROOT / "ui"

FORBIDDEN_TOP_PACKAGES: tuple[str, ...] = (
    "core",
    "prediction",
    "train",
    "models",
)
ALLOWED_CROSS_PACKAGE_PREFIXES: tuple[str, ...] = (
    "services",
    "data.configs",
    "utils",
)


def _iter_ui_py_files() -> list[Path]:
    if not UI_ROOT.is_dir():
        return []
    return sorted(UI_ROOT.rglob("*.py"))


def _violates(import_name: str | None) -> bool:
    if not import_name:
        return False
    head = import_name.split(".")[0]
    return head in FORBIDDEN_TOP_PACKAGES


def test_ui_does_not_import_core_or_prediction_or_train_or_models() -> None:
    offenders: list[str] = []
    for path in _iter_ui_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _violates(alias.name):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}: import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if _violates(node.module):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: "
                        f"from {node.module} import ..."
                    )
    assert offenders == [], (
        "ui/ must not import from core/prediction/train/models. "
        "Offending imports:\n  - " + "\n  - ".join(offenders)
    )


def test_ui_only_uses_allowed_cross_package_imports() -> None:
    """Every cross-package import in ui/ must be from an allowed prefix.

    Stdlib and third-party packages (tkinter, matplotlib, numpy, ...) are
    permitted; the check only fires for first-party packages of this
    repository.
    """
    first_party_top: set[str] = {
        "core", "services", "data", "models", "adapters", "ui",
        "prediction", "train", "utils", "tests", "legacy",
    }
    offenders: list[str] = []
    for path in _iter_ui_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    head = name.split(".")[0]
                    if head not in first_party_top:
                        continue
                    if name.startswith("ui.") or name == "ui":
                        continue
                    if not any(
                        name == p or name.startswith(p + ".")
                        for p in ALLOWED_CROSS_PACKAGE_PREFIXES
                    ):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}: import {name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                if not module:
                    continue
                head = module.split(".")[0]
                if head not in first_party_top:
                    continue
                if module.startswith("ui.") or module == "ui":
                    continue
                if not any(
                    module == p or module.startswith(p + ".")
                    for p in ALLOWED_CROSS_PACKAGE_PREFIXES
                ):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: from {module} import ..."
                    )
    assert offenders == [], (
        "ui/ may only cross-import from "
        f"{ALLOWED_CROSS_PACKAGE_PREFIXES}. Offending imports:\n  - "
        + "\n  - ".join(offenders)
    )
