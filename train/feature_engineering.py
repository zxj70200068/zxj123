"""Feature-engineering for the local short-horizon load forecaster.

This module is intentionally minimal: it converts a list of homogeneous
record dicts (either CSV-row dicts produced by
:class:`core.history.HistoryLogger` or plain Python dicts) into the
``(X, y, feature_names)`` triple consumed by
:func:`train.training_pipeline.train_load_forecaster`.

Feature schema
--------------
The model uses exactly **eight** features, in this fixed order:

1. ``t_out``       -- outdoor dry-bulb temperature [degC]
2. ``hour_sin``    -- ``sin(2*pi*hour/24)`` cyclical encoding of the hour
3. ``hour_cos``    -- ``cos(2*pi*hour/24)`` cyclical encoding of the hour
4. ``is_night``    -- 1.0 if the record is in the night band, else 0.0
5. ``c_sch``       -- schedule coefficient in [0, 1]
6. ``c_occ``       -- occupancy coefficient in [0, 1]
7. ``t_in_prev``   -- previous-step indoor temperature [degC]
8. ``load_prev``   -- previous-step target_load_kw [kW]

The target ``y`` is the **next**-step ``target_load_kw`` in kW. The pairing
(features at index ``i``, target at index ``i+1``) makes the predictor a
one-step-ahead model. The last record produces no training pair.

The function accepts records whose values are either native Python types or
strings (the case for HistoryLogger CSV reads); each field is coerced
defensively so a malformed cell does not abort the entire training run.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

FEATURE_NAMES: list[str] = [
    "t_out",
    "hour_sin",
    "hour_cos",
    "is_night",
    "c_sch",
    "c_occ",
    "t_in_prev",
    "load_prev",
]


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion, returning ``default`` on failure."""
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_bool(value: Any) -> float:
    """Best-effort boolean -> {0.0, 1.0} coercion."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "t"):
            return 1.0
        if v in ("false", "0", "no", "n", "f", ""):
            return 0.0
    return 0.0


def _hour_of(record: dict) -> float:
    """Extract the hour-of-day in [0, 24) from a record.

    Prefers the explicit ``hour`` field; falls back to deriving it from
    ``sim_time_min`` (HistoryLogger schema) when present.
    """
    if "hour" in record and record["hour"] not in ("", None):
        return _to_float(record["hour"], 0.0) % 24.0
    if "sim_time_min" in record and record["sim_time_min"] not in ("", None):
        return (_to_float(record["sim_time_min"], 0.0) / 60.0) % 24.0
    return 0.0


def _target_load_of(record: dict) -> float:
    """Read ``target_load_kw`` from a record, with HistoryLogger fallbacks.

    HistoryLogger CSV rows expose ``load_kw`` (the smoothed required load),
    while plain Python dicts may use ``target_load_kw`` directly.
    """
    if "target_load_kw" in record and record["target_load_kw"] not in ("", None):
        return _to_float(record["target_load_kw"], 0.0)
    if "load_kw" in record and record["load_kw"] not in ("", None):
        return _to_float(record["load_kw"], 0.0)
    return 0.0


def _t_in_of(record: dict) -> float:
    if "t_in" in record and record["t_in"] not in ("", None):
        return _to_float(record["t_in"], 24.0)
    return 24.0


def _features_from_record(record: dict, t_in_prev: float, load_prev: float) -> list[float]:
    hour = _hour_of(record)
    radians = 2.0 * math.pi * hour / 24.0
    return [
        _to_float(record.get("t_out"), 33.5),
        math.sin(radians),
        math.cos(radians),
        _to_bool(record.get("is_night")),
        _to_float(record.get("c_sch"), 1.0),
        _to_float(record.get("c_occ"), 1.0),
        float(t_in_prev),
        float(load_prev),
    ]


def build_feature_frame(records: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Convert a list of records into ``(X, y, feature_names)``.

    Parameters
    ----------
    records : list[dict]
        Either HistoryLogger CSV rows (string-valued) or plain Python dicts.
        Must be ordered chronologically; each adjacent pair ``(records[i],
        records[i+1])`` becomes a training example with features taken from
        ``records[i]`` and target from ``records[i+1]['target_load_kw']``.

    Returns
    -------
    X : np.ndarray
        Float32 matrix of shape ``(n_pairs, 8)``.
    y : np.ndarray
        Float32 vector of shape ``(n_pairs,)`` -- next-step ``target_load_kw``.
    feature_names : list[str]
        Names in the same column order as :data:`FEATURE_NAMES`.
    """
    if not isinstance(records, list) or len(records) < 2:
        return (
            np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            list(FEATURE_NAMES),
        )

    rows: list[list[float]] = []
    targets: list[float] = []
    # Seed previous-step values from the very first record so the first
    # generated pair has well-defined ``t_in_prev`` / ``load_prev``.
    t_in_prev = _t_in_of(records[0])
    load_prev = _target_load_of(records[0])

    for i in range(len(records) - 1):
        rec = records[i]
        nxt = records[i + 1]
        rows.append(_features_from_record(rec, t_in_prev=t_in_prev, load_prev=load_prev))
        targets.append(_target_load_of(nxt))
        # Roll the "previous" state forward for the next iteration.
        t_in_prev = _t_in_of(rec)
        load_prev = _target_load_of(rec)

    X = np.asarray(rows, dtype=np.float32)
    y = np.asarray(targets, dtype=np.float32)
    return X, y, list(FEATURE_NAMES)


__all__ = ["FEATURE_NAMES", "build_feature_frame"]
