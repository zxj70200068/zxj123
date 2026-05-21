"""End-to-end tests for the local load forecaster.

Three sub-tests:

1. ``train_load_forecaster`` writes the joblib bundle and metadata sidecar.
2. ``LoadPredictor`` re-loads the bundle and produces a finite, non-negative
   prediction from a feature dict.
3. ``predict_next_load`` runs without invoking ``random.uniform`` and
   returns a numeric value clamped to ``>= 0``.
"""

from __future__ import annotations

import json
import random as _random
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.pipeline import Pipeline

from models.load_predictor import LoadPredictor
from prediction.load_forecast_service import predict_next_load
from train.feature_engineering import FEATURE_NAMES
from train.training_pipeline import train_load_forecaster


def test_train_load_forecaster_writes_bundle_and_metadata(tmp_path: Path) -> None:
    out_path = tmp_path / "load_forecast_lr.joblib"
    metrics = train_load_forecaster(model_path=out_path)

    assert out_path.exists()
    metadata_path = out_path.with_name(out_path.stem + ".metadata.json")
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["model_path"] == str(out_path)
    assert payload["features"] == list(FEATURE_NAMES)
    assert "trained_at" in payload

    assert np.isfinite(metrics["mae"])
    assert metrics["mae"] < 200.0
    assert metrics["n_samples"] > 0
    assert metrics["features"] == list(FEATURE_NAMES)


def test_load_predictor_predict_dict_and_array(tmp_path: Path) -> None:
    out_path = tmp_path / "load_forecast_lr.joblib"
    train_load_forecaster(model_path=out_path)

    predictor = LoadPredictor(out_path)
    feats = {
        "t_out": 33.5,
        "hour_sin": 0.5,
        "hour_cos": 0.5,
        "is_night": 0.0,
        "c_sch": 1.0,
        "c_occ": 1.0,
        "t_in_prev": 24.0,
        "load_prev": 2000.0,
    }
    y_dict = predictor.predict(feats)
    assert np.isfinite(y_dict)
    assert y_dict >= 0.0

    arr = np.array([feats[name] for name in FEATURE_NAMES], dtype=float)
    y_arr = predictor.predict(arr)
    assert np.isfinite(y_arr)
    assert y_arr >= 0.0
    # dict and array routes must produce the same answer.
    assert abs(y_dict - y_arr) < 1e-6

    # The persisted artefact is the bare ``Pipeline`` instance.
    import joblib
    obj = joblib.load(out_path)
    assert isinstance(obj, Pipeline)
    # Through the predictor, the same Pipeline is reachable in the bundle.
    assert isinstance(predictor._bundle["model"], Pipeline)


def test_predict_next_load_returns_numeric_without_random(tmp_path: Path) -> None:
    out_path = tmp_path / "load_forecast_lr.joblib"
    train_load_forecaster(model_path=out_path)

    state = {
        "t_out": 33.0,
        "hour": 14,
        "is_night": False,
        "c_sch": 1.0,
        "c_occ": 1.0,
        "t_in": 25.0,
        "target_load_kw": 3000.0,
    }

    with patch.object(_random, "uniform") as mock_uniform:
        result = predict_next_load(state, model_path=out_path)
    assert mock_uniform.call_count == 0
    assert isinstance(result, float)
    assert np.isfinite(result)
    assert 0.0 <= result <= 20000.0


def test_predict_next_load_falls_back_when_model_missing(tmp_path: Path) -> None:
    """Missing model file must not raise; it falls back to persistence."""
    missing = tmp_path / "does_not_exist.joblib"
    state = {"target_load_kw": 1234.0, "t_out": 30.0, "hour": 10}
    out = predict_next_load(state, model_path=missing)
    assert out == 1234.0


def test_clear_cache_drops_stale_predictor_after_retrain(tmp_path: Path) -> None:
    """Concern #6: a re-train under the same path must not serve stale weights.

    Without :func:`prediction.load_forecast_service.clear_cache`, the
    process-lifetime ``_predictor_cache`` would keep the first model's
    weights forever. The training pipeline calls clear_cache after each
    write; this test verifies the public API works end-to-end.
    """
    from prediction.load_forecast_service import (
        _predictor_cache,
        clear_cache,
    )

    out_path = tmp_path / "load_forecast_lr.joblib"
    train_load_forecaster(model_path=out_path)

    state = {
        "t_out": 33.0, "hour": 14, "is_night": False,
        "c_sch": 1.0, "c_occ": 1.0,
        "t_in": 25.0, "target_load_kw": 3000.0,
    }
    # Warm the cache with the first model.
    predict_next_load(state, model_path=out_path)
    key = str(out_path.resolve())
    assert key in _predictor_cache, "predictor was not cached after first call"

    # Re-train: the training pipeline calls clear_cache(out_path) on its
    # own. Verify the cache slot for this path was dropped.
    train_load_forecaster(model_path=out_path)
    assert key not in _predictor_cache, (
        "training pipeline did not invalidate the predictor cache "
        "after writing the new joblib bundle"
    )

    # The whole-cache reset path also works.
    predict_next_load(state, model_path=out_path)
    assert key in _predictor_cache
    clear_cache()
    assert _predictor_cache == {}
