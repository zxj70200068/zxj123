"""Public next-step load prediction service.

This module replaces the legacy fake-cloud BiLSTM control strategy with a
real, local, sklearn-backed load forecaster. There is no HTTP call, no
random jitter, no remote endpoint -- the inference path is entirely
deterministic and runs on the edge.

The single public entrypoint, :func:`predict_next_load`, accepts the same
"engine state" dict shape that the legacy cloud strategy consumed and
returns a non-negative float (kW). When the persisted model artefact is
missing on disk, the service degrades gracefully to the previous-step
``target_load_kw`` (a persistence baseline) and logs a warning so the
operator knows the model needs to be retrained.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from models.load_predictor import LoadPredictor, LoadPredictorNotTrainedError
from train.feature_engineering import FEATURE_NAMES
from utils.logging import get_logger

_logger = get_logger(__name__)

DEFAULT_MODEL_PATH = Path("models/saved/load_forecast_lr.joblib")

# Module-level cache so repeated calls inside a single process do not
# re-open the joblib bundle each step.
_predictor_cache: dict[str, LoadPredictor] = {}


def _get_predictor(model_path: Path) -> LoadPredictor:
    key = str(model_path.resolve())
    pred = _predictor_cache.get(key)
    if pred is None:
        pred = LoadPredictor(model_path)
        _predictor_cache[key] = pred
    return pred


def _features_from_state(state: dict[str, Any]) -> dict[str, float]:
    """Build the 8-column feature dict from a runtime engine state.

    Missing keys fall back to physically plausible defaults; this is the
    same defensive contract used by :func:`train.feature_engineering`.
    """
    hour = float(state.get("hour", 12.0)) % 24.0
    radians = 2.0 * math.pi * hour / 24.0
    is_night = state.get("is_night", False)
    is_night_f = 1.0 if bool(is_night) else 0.0

    # ``t_in_prev`` / ``load_prev`` mirror the lagged-state contract used in
    # build_feature_frame: callers may pass them explicitly, otherwise we
    # derive them from the current snapshot.
    t_in_prev = float(state.get("t_in_prev", state.get("t_in", 24.0)))
    load_prev = float(state.get("load_prev", state.get("target_load_kw", 0.0)))

    return {
        "t_out": float(state.get("t_out", 33.5)),
        "hour_sin": math.sin(radians),
        "hour_cos": math.cos(radians),
        "is_night": is_night_f,
        "c_sch": float(state.get("c_sch", 1.0)),
        "c_occ": float(state.get("c_occ", 1.0)),
        "t_in_prev": t_in_prev,
        "load_prev": load_prev,
    }


def predict_next_load(
    state: dict[str, Any],
    model_path: str | Path | None = None,
) -> float:
    """Predict the next-step cooling load in kW.

    Parameters
    ----------
    state : dict
        Engine state snapshot. Recognised keys: ``t_out``, ``hour``,
        ``is_night``, ``c_sch``, ``c_occ``, ``t_in``, ``target_load_kw``,
        plus optional lagged ``t_in_prev`` / ``load_prev``. Any subset is
        tolerated; defaults are physically plausible.
    model_path : str or Path, optional
        Override the persisted artefact location. Defaults to
        :data:`DEFAULT_MODEL_PATH`.

    Returns
    -------
    float
        Next-step load forecast in kW, clamped to ``>= 0``. If the model
        artefact is missing, the function logs a warning and returns the
        current ``state['target_load_kw']`` (or 0.0) as a persistence
        fallback. No exceptions propagate to the control chain.
    """
    path = Path(model_path) if model_path is not None else DEFAULT_MODEL_PATH
    fallback = max(0.0, float(state.get("target_load_kw", 0.0)))

    try:
        predictor = _get_predictor(path)
        feats = _features_from_state(state)
        # Defensive: ensure the feature dict matches the model's expected
        # schema. ``LoadPredictor.predict`` will raise if anything is off.
        for name in FEATURE_NAMES:
            feats.setdefault(name, 0.0)
        return float(predictor.predict(feats))
    except LoadPredictorNotTrainedError as exc:
        _logger.warning(
            "predict_next_load: model artefact missing (%s); "
            "falling back to persistence baseline (%.1f kW)",
            exc, fallback,
        )
        return fallback
    except Exception:
        _logger.exception(
            "predict_next_load: prediction failed; "
            "falling back to persistence baseline"
        )
        return fallback


__all__ = ["predict_next_load", "DEFAULT_MODEL_PATH"]
