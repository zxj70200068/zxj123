"""Offline training pipeline for the local short-horizon load forecaster.

This module exposes :func:`train_load_forecaster`, which fits a small
``Ridge`` regression inside an ``sklearn`` ``Pipeline`` (StandardScaler then
Ridge) on either a caller-supplied list of records or
:func:`train.datasets.make_synthetic_dataset`. It then persists the fitted
pipeline via ``joblib.dump`` together with a sidecar metadata JSON file
describing the feature schema, training timestamp and metrics.

The persisted bundle is the **single artefact** consumed by
:class:`models.load_predictor.LoadPredictor` at inference time. It contains:

* ``model``        -- the fitted ``Pipeline`` instance.
* ``features``     -- the ordered feature-name list used during training.
* ``schema_version`` -- bumped whenever the feature schema changes.
* ``metrics``      -- training-set MAE / R^2 (a smoke-test for the artefact).
* ``trained_at``   -- ISO-8601 UTC timestamp.

Run as a script
---------------
``python -m train.training_pipeline --output models/saved/load_forecast_lr.joblib``

Re-runs the training on the synthetic dataset and overwrites the artefact
in place. This is what FEAT-003 step 17 invokes to materialise the
checked-in placeholder model.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from train.datasets import make_synthetic_dataset
from train.feature_engineering import build_feature_frame
from train.model_export import export_metadata
from utils.logging import get_logger

_logger = get_logger(__name__)

SCHEMA_VERSION = "1.0"
DEFAULT_MODEL_PATH = Path("models/saved/load_forecast_lr.joblib")


def _build_pipeline() -> Pipeline:
    """Construct the fixed StandardScaler + Ridge pipeline."""
    return Pipeline([
        ("scaler", StandardScaler()),
        ("reg", Ridge(alpha=1.0)),
    ])


def train_load_forecaster(
    records: list[dict] | None = None,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> dict[str, Any]:
    """Fit a Ridge load forecaster and persist it to ``model_path``.

    Parameters
    ----------
    records : list[dict] or None, default None
        Training records. When ``None``, the synthetic dataset
        (:func:`train.datasets.make_synthetic_dataset`) is used; this keeps
        the training run self-contained for unit tests and bootstrap
        deployments.
    model_path : str or pathlib.Path, default ``models/saved/load_forecast_lr.joblib``
        Output path for the joblib bundle. Parent directories are created
        if missing. A sibling ``<stem>.metadata.json`` is also written.

    Returns
    -------
    dict
        ``{'mae', 'r2', 'n_samples', 'features', 'model_path'}``. ``mae``
        and ``r2`` are evaluated on the training set, sufficient as a
        smoke metric for the placeholder model.
    """
    if records is None:
        records = make_synthetic_dataset()

    X, y, feature_names = build_feature_frame(records)
    if X.shape[0] == 0:
        raise ValueError("training records produced an empty feature matrix")

    pipeline = _build_pipeline()
    pipeline.fit(X, y)
    y_pred = pipeline.predict(X)

    mae = float(mean_absolute_error(y, y_pred))
    r2 = float(r2_score(y, y_pred)) if np.var(y) > 0 else 0.0

    out_path = Path(model_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Persist the bare ``Pipeline`` so ``joblib.load(path)`` round-trips
    # to a sklearn estimator directly. Schema and provenance live in the
    # sidecar ``.metadata.json`` written by :func:`export_metadata` below.
    joblib.dump(pipeline, out_path)

    # Invalidate any in-process LoadPredictor cache so the running edge
    # process picks up the freshly trained weights without restart
    # (concern #6 from the v1 review). The import is local to avoid a
    # cyclic dependency between train.* and prediction.*.
    try:
        from prediction.load_forecast_service import clear_cache as _clear
        _clear(out_path)
    except Exception:  # pragma: no cover - defensive
        _logger.exception(
            "train_load_forecaster: failed to invalidate predictor cache; "
            "running processes may serve stale weights until restart"
        )

    trained_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    metrics = {
        "mae": mae,
        "r2": r2,
        "n_samples": int(X.shape[0]),
        "features": list(feature_names),
        "model_path": str(out_path),
        "schema_version": SCHEMA_VERSION,
        "trained_at": trained_at,
    }
    export_metadata(out_path, metrics)
    _logger.info(
        "train_load_forecaster: wrote %s (n=%d, mae=%.2f, r2=%.3f)",
        out_path, X.shape[0], mae, r2,
    )
    return metrics


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the local load forecaster")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_MODEL_PATH),
        help="Output joblib path (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    metrics = train_load_forecaster(model_path=args.output)
    print(
        f"trained: n_samples={metrics['n_samples']} "
        f"mae={metrics['mae']:.2f}kW r2={metrics['r2']:.3f} "
        f"-> {metrics['model_path']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(_main())


__all__ = ["train_load_forecaster", "DEFAULT_MODEL_PATH", "SCHEMA_VERSION"]
