"""Synthetic dataset generators for offline training.

This package exposes a single deterministic generator,
:func:`make_synthetic_dataset`, used by
:func:`train.training_pipeline.train_load_forecaster` whenever no on-disk
HistoryLogger CSV is provided. The generator is a *placeholder* that
produces a realistic-shaped diurnal load profile so the training pipeline
runs (and unit tests stay deterministic) before any real plant data is
collected.

In production, this is replaced with a real CSV reader that materialises
:class:`core.history.HistoryLogger` rows from
``data/history/history_log.csv``.
"""

from __future__ import annotations

import math

import numpy as np

# Keep the feature columns we synthesise aligned with the schema consumed by
# :func:`train.feature_engineering.build_feature_frame`.
__all__ = ["make_synthetic_dataset"]


def make_synthetic_dataset(n_samples: int = 720, seed: int = 42) -> list[dict]:
    """Generate ``n_samples`` chronologically-ordered records.

    The signal is a smooth diurnal cooling-load profile modulated by outdoor
    temperature plus a small white-noise term so the regressor has a
    non-trivial, but deterministic, learning signal.

    Parameters
    ----------
    n_samples : int, default 720
        Number of records to emit. With a 15-minute step, 720 = 7.5 days of
        synthetic operation; the default of 720 is large enough for a
        Ridge regression to stabilise yet small enough for unit tests
        (< 1 second to train on a developer laptop).
    seed : int, default 42
        Seed for the NumPy RNG. Determinism is required by the test suite.

    Returns
    -------
    list[dict]
        One dict per simulated 15-minute step. Keys include the columns
        consumed by :func:`build_feature_frame` plus the supervisory
        ``target_load_kw`` target column.
    """
    if n_samples < 2:
        raise ValueError("n_samples must be >= 2 to form at least one pair")

    rng = np.random.default_rng(seed)
    dt_min = 15
    records: list[dict] = []

    # Day-over-day weather variation so the model sees a non-trivial ``t_out``
    # distribution (28 to 38 degC roughly, peaking mid-afternoon).
    base_load_kw = 2200.0
    peak_amp_kw = 3500.0

    t_in_prev = 24.0
    for i in range(n_samples):
        sim_time_min = i * dt_min
        hour = (sim_time_min / 60.0) % 24.0
        # Day index (0-based) modulates the daily peak temperature.
        day_idx = sim_time_min // (60 * 24)
        day_peak_t = 33.5 + 1.5 * math.sin(0.6 * day_idx)

        # Outdoor temperature: sinusoid peaking at hour=15 with a small jitter.
        t_out = day_peak_t + 4.0 * math.sin(2.0 * math.pi * (hour - 9.0) / 24.0)
        t_out += float(rng.normal(0.0, 0.3))

        # Schedule and occupancy: ramp up at 7am, ramp down at 19h.
        if 7.0 <= hour < 19.0:
            c_sch = 1.0
            c_occ = float(np.clip(0.55 + 0.4 * math.sin(math.pi * (hour - 7.0) / 12.0), 0.0, 1.0))
            is_night = False
        else:
            c_sch = 0.2 if (hour < 7.0 or hour >= 22.0) else 0.55
            c_occ = 0.05
            is_night = (hour >= 22.0) or (hour < 6.0)

        # Synthetic target load: diurnal envelope + weather modulation + noise.
        diurnal = 0.5 * (1.0 + math.sin(math.pi * (hour - 9.0) / 12.0))
        diurnal = max(0.0, diurnal)
        weather_factor = 1.0 + 0.04 * (t_out - 33.5)
        noise = float(rng.normal(0.0, 80.0))
        target_load_kw = max(
            0.0,
            base_load_kw * c_sch * 0.5
            + peak_amp_kw * diurnal * c_sch * c_occ * weather_factor
            + noise,
        )

        # Indoor temperature drifts slightly with the load (purely synthetic).
        t_in = float(np.clip(
            t_in_prev + 0.01 * (target_load_kw / 4000.0 - 0.5) + rng.normal(0.0, 0.05),
            21.0,
            27.5,
        ))
        t_in_prev = t_in

        records.append({
            "sim_time_min": sim_time_min,
            "hour": hour,
            "t_out": round(t_out, 3),
            "t_in": round(t_in, 3),
            "c_sch": round(c_sch, 3),
            "c_occ": round(c_occ, 3),
            "is_night": is_night,
            "target_load_kw": round(target_load_kw, 2),
        })

    return records
