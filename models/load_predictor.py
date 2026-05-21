"""Inference wrapper around a persisted scikit-learn load forecaster.

This module is the **only** way the runtime control loop reads the trained
load forecaster. It enforces:

* Lazy loading -- the joblib bundle is opened on the first :meth:`predict`
  call, so importing this module never touches the filesystem.
* Strict input validation -- a feature dict must contain every column from
  :data:`train.feature_engineering.FEATURE_NAMES`. Numpy arrays must be
  one-dimensional and the right length.
* No external IO -- there are no HTTP calls, no LLM, no random sampling.

If the persisted artefact is missing, a :class:`LoadPredictorNotTrainedError`
is raised at predict time so callers (e.g.
:mod:`prediction.load_forecast_service`) can fall back to a persistence
baseline rather than crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from train.feature_engineering import FEATURE_NAMES
from utils.logging import get_logger

_logger = get_logger(__name__)


class LoadPredictorNotTrainedError(RuntimeError):
    """Raised when :class:`LoadPredictor` cannot find or load its artefact."""


class LoadPredictor:
    """Light wrapper around a persisted ``Pipeline`` regressor.

    Parameters
    ----------
    model_path : str or Path
        Path to a joblib bundle produced by
        :func:`train.training_pipeline.train_load_forecaster`. The bundle
        is expected to be a dict with at least a ``model`` key holding the
        fitted estimator and a ``features`` key holding the column order.
    """

    def __init__(self, model_path: str | Path) -> None:
        self.model_path = Path(model_path)
        self._bundle: dict[str, Any] | None = None
        self._features: list[str] = list(FEATURE_NAMES)
        self._loaded = False

    # ------------------------------------------------------------------ load
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self.model_path.exists():
            raise LoadPredictorNotTrainedError(
                f"load forecaster artefact not found at {self.model_path!s}; "
                "run `python -m train.training_pipeline` to generate it"
            )
        try:
            obj = joblib.load(self.model_path)
        except Exception as exc:
            raise LoadPredictorNotTrainedError(
                f"failed to load {self.model_path!s}: {exc}"
            ) from exc

        # Two on-disk layouts are supported:
        # 1. Bare estimator (current default written by training_pipeline).
        # 2. Legacy dict bundle ``{'model': estimator, 'features': [...]}``.
        if isinstance(obj, dict) and "model" in obj:
            self._bundle = dict(obj)
            features = obj.get("features")
            if isinstance(features, list) and features:
                self._features = list(features)
        else:
            self._bundle = {"model": obj}

        # When persisting a bare estimator, the feature schema lives in the
        # sidecar metadata JSON. Read it if present so the dict-input path
        # of :meth:`predict` validates against the right column set.
        meta_path = self.model_path.with_name(self.model_path.stem + ".metadata.json")
        if meta_path.exists():
            try:
                import json as _json
                with open(meta_path, encoding="utf-8") as f:
                    meta = _json.load(f)
                feats = meta.get("features")
                if isinstance(feats, list) and feats:
                    self._features = list(feats)
            except Exception:
                _logger.exception(
                    "LoadPredictor: failed to parse %s; using built-in schema",
                    meta_path,
                )
        self._loaded = True

    # ----------------------------------------------------------------- helpers
    @property
    def features(self) -> list[str]:
        """Feature column names in the order the model was trained on."""
        if not self._loaded:
            self._ensure_loaded()
        return list(self._features)

    def _vectorise(self, features: dict | np.ndarray) -> np.ndarray:
        if isinstance(features, np.ndarray):
            arr = np.asarray(features, dtype=np.float64).reshape(-1)
            if arr.shape[0] != len(self._features):
                raise ValueError(
                    f"expected feature vector of length {len(self._features)}, "
                    f"got {arr.shape[0]}"
                )
            return arr.reshape(1, -1)
        if isinstance(features, dict):
            try:
                row = [float(features[name]) for name in self._features]
            except KeyError as exc:
                raise ValueError(
                    f"feature dict is missing key {exc.args[0]!r}; "
                    f"required keys: {self._features}"
                ) from exc
            return np.asarray([row], dtype=np.float64)
        raise TypeError(
            "features must be a dict or 1-D numpy.ndarray, "
            f"got {type(features).__name__}"
        )

    # ---------------------------------------------------------------- predict
    def predict(self, features: dict | np.ndarray) -> float:
        """Return the next-step load prediction in kW (clamped to >= 0).

        Parameters
        ----------
        features : dict or numpy.ndarray
            A feature dict keyed by :data:`FEATURE_NAMES`, or a 1-D numpy
            array in the same column order.
        """
        self._ensure_loaded()
        assert self._bundle is not None  # for type-checkers
        x = self._vectorise(features)
        y_hat = float(self._bundle["model"].predict(x)[0])
        return max(0.0, y_hat)


__all__ = ["LoadPredictor", "LoadPredictorNotTrainedError"]
