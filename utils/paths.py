"""Filesystem path helpers anchored at the project root."""

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
MODELS_DIR: Path = PROJECT_ROOT / "models"
HISTORY_DIR: Path = DATA_DIR / "history"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing and return it."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
