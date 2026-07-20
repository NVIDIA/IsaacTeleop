# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LocomotionRootCmdRetargeter — hip-height integration uses real
elapsed time from ``ComputeContext.graph_time``, so the result is invariant to
the control rate (60/90/120 Hz)."""

import math

from isaacteleop.retargeters.locomotion_retargeter import (
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
)
from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    ExecutionEvents,
    GraphTime,
    OptionalTensorGroup,
    OptionalType,
    TensorGroup,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
)


def _make_controller_group(thumbstick_y: float) -> OptionalTensorGroup:
    """Build a ``controller_*`` input with only the thumbstick fields set —
    those are the only fields the locomotion retargeter reads. Writing any
    field flips ``is_none`` to False."""
    group = OptionalTensorGroup(OptionalType(ControllerInput()))
    group[ControllerInputIndex.THUMBSTICK_X] = 0.0
    group[ControllerInputIndex.THUMBSTICK_Y] = thumbstick_y
    return group


def _make_output_group() -> TensorGroup:
    return TensorGroup(
        TensorGroupType(
            "root_command",
            [NDArrayType("command", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32)],
        )
    )


def _run_at_rate(rate_hz: float, duration_s: float, right_y: float) -> float:
    """Drive the retargeter at ``rate_hz`` for ``duration_s`` with a constant
    right-stick Y value. Returns the final hip height."""
    config = LocomotionRootCmdRetargeterConfig(
        initial_hip_height=0.72,
        rotation_scale=0.35,
    )
    r = LocomotionRootCmdRetargeter(config, name="locomotion")

    period_s = 1.0 / rate_hz
    period_ns = int(round(period_s * 1e9))
    n_steps = int(round(duration_s / period_s))

    inputs = {
        "controller_left": _make_controller_group(0.0),
        "controller_right": _make_controller_group(right_y),
    }
    outputs = {"root_command": _make_output_group()}

    t_ns = 0
    for _ in range(n_steps):
        ctx = ComputeContext(graph_time=GraphTime(sim_time_ns=t_ns, real_time_ns=t_ns))
        r._compute_fn(inputs, outputs, ctx)
        t_ns += period_ns

    return float(outputs["root_command"][0][3])


class TestLocomotionDtIntegration:
    """Hip-height integration is rate-invariant when dt is derived from
    ``GraphTime``."""

    def test_hip_height_matches_across_rates(self):
        """Equal wall-clock duration with the same stick value should produce
        the same hip-height delta at 60, 90, and 120 Hz."""
        duration_s = 1.0
        right_y = 0.5

        h60 = _run_at_rate(60.0, duration_s, right_y)
        h90 = _run_at_rate(90.0, duration_s, right_y)
        h120 = _run_at_rate(120.0, duration_s, right_y)

        # 60Hz integrates the first frame with the nominal fallback dt (1/60),
        # so we tolerate ~1 frame of drift at the highest rate. The point is
        # that 90/120 Hz are NOT scaled by their period mismatch with 60 Hz
        # (which would have produced 1.5x / 2x the delta).
        tol = 1.0 / 60.0 * 0.35 * abs(right_y) + 1e-6
        assert math.isclose(h60, h90, abs_tol=tol), (h60, h90)
        assert math.isclose(h60, h120, abs_tol=tol), (h60, h120)
        assert math.isclose(h90, h120, abs_tol=tol), (h90, h120)

    def test_hip_height_unchanged_when_stick_zero(self):
        """Zero thumbstick input must leave hip height at the configured initial."""
        config = LocomotionRootCmdRetargeterConfig(initial_hip_height=0.72)
        r = LocomotionRootCmdRetargeter(config, name="locomotion")

        inputs = {
            "controller_left": _make_controller_group(0.0),
            "controller_right": _make_controller_group(0.0),
        }
        outputs = {"root_command": _make_output_group()}

        for i in range(60):
            t_ns = i * (1_000_000_000 // 60)
            ctx = ComputeContext(
                graph_time=GraphTime(sim_time_ns=t_ns, real_time_ns=t_ns)
            )
            r._compute_fn(inputs, outputs, ctx)

        # Output is float32, so allow one ulp of round-trip slack from 0.72.
        assert math.isclose(float(outputs["root_command"][0][3]), 0.72, abs_tol=1e-6)

    def test_reset_clears_previous_timestamp(self):
        """After a reset, the next step uses the fallback dt rather than a
        huge gap from the pre-reset timestamp."""
        config = LocomotionRootCmdRetargeterConfig(
            initial_hip_height=0.72,
            rotation_scale=0.35,
        )
        r = LocomotionRootCmdRetargeter(config, name="locomotion")

        inputs = {
            "controller_left": _make_controller_group(0.0),
            "controller_right": _make_controller_group(1.0),
        }
        outputs = {"root_command": _make_output_group()}

        # Advance the clock by 10 seconds across two steps.
        t_a = 0
        t_b = 10_000_000_000  # 10s later
        ctx_a = ComputeContext(graph_time=GraphTime(sim_time_ns=t_a, real_time_ns=t_a))
        r._compute_fn(inputs, outputs, ctx_a)

        # Reset between steps: the next step should NOT integrate over the
        # 10-second gap, only over the fallback dt.
        ctx_b = ComputeContext(
            graph_time=GraphTime(sim_time_ns=t_b, real_time_ns=t_b),
            execution_events=ExecutionEvents(reset=True),
        )
        r._compute_fn(inputs, outputs, ctx_b)
        h_after_reset = float(outputs["root_command"][0][3])

        # After reset, the integration starts from initial_hip_height and uses
        # the fallback dt for this frame — NOT the 10s gap from the prior step.
        # Output rounds to float32, so use a tolerance compatible with that.
        expected = 0.72 + 1.0 * config.fallback_dt * 0.35
        assert math.isclose(h_after_reset, expected, abs_tol=1e-5), h_after_reset
        # And verify it is nowhere near what 10s of integration would produce
        # (which would saturate at the 1.0 hip ceiling).
        assert h_after_reset < 0.73
