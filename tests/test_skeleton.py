"""Skeleton smoke tests: package imports, legacy isolation, and root files exist."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TOP_LEVEL_PACKAGES = (
    "core",
    "services",
    "models",
    "adapters",
    "ui",
    "data",
    "train",
    "prediction",
    "utils",
)

# Directories where we ban references to the legacy module.
NEW_CODE_DIRS = (
    "core",
    "services",
    "models",
    "adapters",
    "prediction",
    "train",
    "utils",
    "ui",
)


def test_new_packages_import_cleanly() -> None:
    """Every new top-level package imports without error."""
    for pkg in NEW_TOP_LEVEL_PACKAGES:
        importlib.import_module(pkg)


def test_legacy_module_exists_but_is_not_referenced_by_new_code() -> None:
    """``legacy`` is importable, but no new module references ``main_ui_legacy``."""
    legacy = importlib.import_module("legacy")
    assert legacy is not None

    offenders: list[str] = []
    for top in NEW_CODE_DIRS:
        top_dir = REPO_ROOT / top
        if not top_dir.is_dir():
            continue
        for py_file in top_dir.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # pragma: no cover - defensive
                continue
            if "main_ui_legacy" in text:
                offenders.append(str(py_file.relative_to(REPO_ROOT)))

    assert offenders == [], f"new code references legacy module: {offenders}"


@pytest.mark.parametrize("filename", ["pyproject.toml", "requirements.txt"])
def test_root_project_files_exist(filename: str) -> None:
    """Mandatory project files live at the repo root."""
    assert (REPO_ROOT / filename).is_file(), f"missing root file: {filename}"
