"""Unit tests for :mod:`core.physics.thermal`."""

from __future__ import annotations

from core.physics.thermal import RoomRCModel, ThermalBuffer


def test_thermal_buffer_monotonic_approach_to_constant_target() -> None:
    """Repeated steps with a constant target converge monotonically toward it."""
    buf = ThermalBuffer()
    target = 1000.0
    # First call seeds with the target itself.
    first = buf.step(target_load=target, dt_min=15.0, tau_min=60.0, reset=True)
    assert first == target

    # Now drive from a lower starting point: emulate by manually setting
    # prev_load and observing that successive steps approach the new target.
    buf.prev_load = 0.0
    prev_distance = abs(target - 0.0)
    for _ in range(20):
        new_value = buf.step(target_load=target, dt_min=15.0, tau_min=60.0)
        new_distance = abs(target - new_value)
        # First-order low-pass: distance to target must be (weakly) decreasing.
        assert new_distance <= prev_distance + 1e-6
        # And it must converge below the original gap.
        prev_distance = new_distance

    # After 20 steps with dt/(tau+dt)=15/75=0.2 the gap is below 5% of the
    # original 1000 kW gap.
    assert prev_distance < 0.05 * 1000.0


def test_room_rc_model_drifts_toward_outdoor_when_no_cooling() -> None:
    """With ``q_cooling_delivered_kw == q_load_kw`` the indoor temp drifts
    toward the outdoor temp via envelope conduction only."""
    config = {"rc_model_params": {"heat_gain_coeff": 0.001, "envelope_ua_coeff": 0.015}}
    room = RoomRCModel(config)
    room.t_in = 24.0
    t_out = 35.0  # hot day
    initial = room.t_in
    # Step 1 hour with zero net load: only the envelope term is active.
    new_t = room.step(t_out=t_out, q_load_kw=0.0, q_cooling_delivered_kw=0.0, dt_min=60.0)
    assert new_t > initial, f"expected indoor temp to rise toward t_out, got {new_t}"
    assert new_t < t_out, "envelope conduction should not overshoot the outdoor temp"


def test_room_rc_model_cool_outdoor_pulls_indoor_down() -> None:
    """Symmetric: with cool outdoor and zero net load, indoor falls toward it."""
    config = {"rc_model_params": {"heat_gain_coeff": 0.001, "envelope_ua_coeff": 0.015}}
    room = RoomRCModel(config)
    room.t_in = 28.0
    t_out = 18.0
    new_t = room.step(t_out=t_out, q_load_kw=0.0, q_cooling_delivered_kw=0.0, dt_min=60.0)
    assert new_t < 28.0
    assert new_t > t_out
