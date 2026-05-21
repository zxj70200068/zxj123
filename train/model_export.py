"""Sidecar metadata writer for trained model artefacts.

Each fitted model bundle (``models/saved/<name>.joblib``) is paired with a
sibling ``<name>.metadata.json`` that records the feature schema, metrics
and a training timestamp. Edge deployments validate the bundle against
this metadata before serving.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_metadata(
    model_path: str | Path,
    metrics: dict[str, Any],
    out_path: str | Path | None = None,
) -> Path:
    """Write a JSON metadata sidecar next to ``model_path``.

    Parameters
    ----------
    model_path : str or Path
        Path of the joblib bundle. Its stem (with ``.metadata.json``
        suffix) is used as the default ``out_path``.
    metrics : dict
        Free-form dict of metrics / schema info to persist verbatim.
    out_path : str or Path, optional
        Override the metadata destination. When given, the parent
        directory is created if missing.

    Returns
    -------
    pathlib.Path
        The path that was written.
    """
    model_path = Path(model_path)
    if out_path is None:
        out_path = model_path.with_name(model_path.stem + ".metadata.json")
    else:
        out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"model_path": str(model_path), **dict(metrics)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out_path


__all__ = ["export_metadata"]
