# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pinch-proximity haptic feedback: feel each finger approach the thumb.

Reads XR hand-tracking joint poses, computes the Euclidean distance between
each finger tip and the thumb tip for both hands, and ramps that distance
into per-finger vibration amplitudes. The closer the finger tip is to the
thumb tip, the stronger both the finger *and* the thumb vibrate -- so when
you actually touch them together you get a maximum-intensity pulse on both.

Pipeline (default ``--device manus``):

::

    HandsSource (left + right)
        |
        v
    PinchProximityToFingerPower (per side; HandInput -> FingerPowerVector(5))
        |
        v
    HapticSink(ManusHapticDevice())

For users without Manus gloves, ``--device openxr_controller`` collapses each
per-side ``FingerPowerVector(5)`` to a single ``ControllerHapticPulse`` (max
across fingers) and routes it through the OpenXR controller haptic stack.
This is useful as a hardware smoke test or when running on a Quest with
hand-tracking enabled but no Manus available.

The retargeter is intentionally vendor-neutral: it produces
``FingerPowerVector(num_fingers=5)`` per the
``isaacteleop.retargeting_engine.tensor_types.tactile_types`` schema, and
any ``IHapticDevice`` whose ``accepted_type()`` is that schema can be wired
into the same sink without changing the per-side mapper.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import numpy as np

from isaacteleop.haptic_devices.manus import ManusHapticDevice
from isaacteleop.haptic_devices.openxr_controller import (
    OpenXRControllerHapticDevice,
    OpenXRControllerHapticSource,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    HandsSource,
    HapticSink,
)
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OutputCombiner,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulse,
    ControllerHapticPulseField,
    FingerIndex,
    FingerPowerVector,
    HandInput,
    HandInputIndex,
    HandJointIndex,
    NUM_CONTROLLER_HAPTIC_FIELDS,
    NUM_HAPTIC_FINGERS,
)
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig


# Maps each non-thumb finger in FingerPowerVector to its OpenXR fingertip joint.
# `FingerIndex.THUMB` is intentionally absent: the thumb pad's vibration mirrors
# the strongest non-thumb finger's pinch (filled in `_compute_fn` after this
# loop), so iterating only the four other fingers here keeps the logic linear.
_FINGER_TIP_JOINTS: dict[FingerIndex, HandJointIndex] = {
    FingerIndex.INDEX: HandJointIndex.INDEX_TIP,
    FingerIndex.MIDDLE: HandJointIndex.MIDDLE_TIP,
    FingerIndex.RING: HandJointIndex.RING_TIP,
    FingerIndex.PINKY: HandJointIndex.LITTLE_TIP,
}


# ============================================================================
# Pinch retargeter -- HandInput -> FingerPowerVector
# ============================================================================


class PinchProximityToFingerPower(BaseRetargeter):
    """Per-hand: distance(thumb_tip, finger_tip) -> per-finger vibration intensity.

    Inputs:
        - ``"hand"``: optional :func:`HandInput <isaacteleop.retargeting_engine.tensor_types.HandInput>`
          -- when absent (hand not tracked), the output is all zeros.

    Outputs:
        - ``"powers"``: :func:`FingerPowerVector(5) <isaacteleop.retargeting_engine.tensor_types.FingerPowerVector>`
          in ``[0, saturation]`` (Manus-compatible order:
          ``[Thumb, Index, Middle, Ring, Pinky]``).

    Math:
        For each non-thumb finger ``f``::

            d_f = ||joint_pos[f_tip] - joint_pos[THUMB_TIP]||
            x   = (max_distance_m - d_f) / (max_distance_m - min_distance_m)
            powers[f] = clip(x ** falloff_exponent, 0.0, saturation)

        The thumb's slot is filled with the max across the four other fingers,
        so any pinch event the user feels on a finger is also felt on the
        thumb -- the intuitive "both sides of the pinch buzz" behaviour.

    Tunables are exposed as constructor arguments (not ``ParameterState``)
    because this is an example retargeter; the production tuning UI integration
    lives on the :mod:`~isaacteleop.retargeters.tactile_retargeters` mappers.
    """

    INPUT_HAND = "hand"
    OUTPUT_POWERS = "powers"

    def __init__(
        self,
        name: str,
        max_distance_m: float = 0.10,
        min_distance_m: float = 0.005,
        saturation: float = 1.0,
        falloff_exponent: float = 1.0,
    ) -> None:
        if max_distance_m <= min_distance_m:
            raise ValueError(
                f"PinchProximityToFingerPower '{name}': "
                f"max_distance_m ({max_distance_m}) must be > min_distance_m ({min_distance_m})"
            )
        if not 0.0 <= saturation <= 1.0:
            raise ValueError(
                f"PinchProximityToFingerPower '{name}': saturation must be in [0, 1], got {saturation}"
            )
        if falloff_exponent <= 0.0:
            raise ValueError(
                f"PinchProximityToFingerPower '{name}': falloff_exponent must be > 0, got {falloff_exponent}"
            )

        self._max_distance_m = float(max_distance_m)
        self._min_distance_m = float(min_distance_m)
        self._saturation = float(saturation)
        self._falloff_exponent = float(falloff_exponent)
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_HAND: OptionalType(HandInput())}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_POWERS: FingerPowerVector(NUM_HAPTIC_FINGERS)}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        powers = np.zeros(NUM_HAPTIC_FINGERS, dtype=np.float32)

        hand = inputs[self.INPUT_HAND]
        if hand.is_none:
            outputs[self.OUTPUT_POWERS][0] = powers
            return

        joint_positions = np.asarray(hand[HandInputIndex.JOINT_POSITIONS])
        joint_valid = np.asarray(hand[HandInputIndex.JOINT_VALID])

        # Bail cleanly if the thumb tip itself is not valid -- without it we
        # have nothing meaningful to measure against.
        if not bool(joint_valid[HandJointIndex.THUMB_TIP]):
            outputs[self.OUTPUT_POWERS][0] = powers
            return

        thumb_tip = joint_positions[HandJointIndex.THUMB_TIP]
        denom = self._max_distance_m - self._min_distance_m

        max_finger_power = 0.0
        for finger_idx, tip_joint in _FINGER_TIP_JOINTS.items():
            if not bool(joint_valid[tip_joint]):
                # Skip invalid joints; the corresponding power stays at zero.
                continue
            distance = float(np.linalg.norm(joint_positions[tip_joint] - thumb_tip))
            # Map distance to [0, 1]: 0 at >= max_distance, 1 at <= min_distance.
            ratio = (self._max_distance_m - distance) / denom
            ratio = max(0.0, min(1.0, ratio))
            # Apply falloff (exponent < 1 makes the response feel stronger near
            # the threshold; > 1 makes only very-close pinches feel anything).
            shaped = ratio**self._falloff_exponent
            power = min(self._saturation, max(0.0, shaped))
            powers[finger_idx] = power
            if power > max_finger_power:
                max_finger_power = power

        # Both sides of the pinch buzz: thumb mirrors the strongest finger
        # signal so the user feels the pinch on both pads.
        powers[FingerIndex.THUMB] = max_finger_power
        outputs[self.OUTPUT_POWERS][0] = powers


class FingerPowerToControllerPulse(BaseRetargeter):
    """Collapse a :func:`FingerPowerVector` to one :func:`ControllerHapticPulse`.

    Single-channel adapter for users routing pinch feedback to an OpenXR
    motion controller (one motor per hand). Takes the max across fingers --
    matches "the most-pinched finger drives the rumble" intuition.

    Pure shim, no tunables -- frequency / duration come from the constructor
    so the controller-side pulse parameters are still configurable but the
    amplitude is unmodified from the FingerPowerVector input.
    """

    INPUT_POWERS = "powers"
    OUTPUT_PULSE = "pulse"

    def __init__(
        self,
        name: str,
        frequency_hz: float = 0.0,
        duration_s: float = 0.0,
        num_fingers: int = NUM_HAPTIC_FINGERS,
    ) -> None:
        self._frequency_hz = float(frequency_hz)
        self._duration_s = float(duration_s)
        self._num_fingers = int(num_fingers)
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_POWERS: FingerPowerVector(self._num_fingers)}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_PULSE: ControllerHapticPulse()}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        powers = np.asarray(inputs[self.INPUT_POWERS][0], dtype=np.float32)
        amplitude = float(powers.max()) if powers.size else 0.0
        pulse = np.zeros(NUM_CONTROLLER_HAPTIC_FIELDS, dtype=np.float32)
        pulse[ControllerHapticPulseField.AMPLITUDE] = amplitude
        pulse[ControllerHapticPulseField.FREQUENCY_HZ] = self._frequency_hz
        pulse[ControllerHapticPulseField.DURATION_S] = self._duration_s
        outputs[self.OUTPUT_PULSE][0] = pulse


# ============================================================================
# Pipeline builders
# ============================================================================


def _build_manus_pipeline(
    hands: HandsSource,
    *,
    max_distance_m: float,
    min_distance_m: float,
    saturation: float,
    falloff_exponent: float,
):
    """Pinch-proximity -> per-finger powers -> Manus glove vibration.

    Returns:
        Tuple of (OutputCombiner, monitoring) where monitoring is a dict of
        ``OutputSelector``s keyed ``"powers_<side>"`` (FingerPowerVector) so
        the main loop can read per-finger amplitudes for display.
    """
    sink_inputs: dict[str, Any] = {}
    monitoring: dict[str, Any] = {}

    for side, hands_output in (
        ("left", HandsSource.LEFT),
        ("right", HandsSource.RIGHT),
    ):
        mapper = PinchProximityToFingerPower(
            f"{side}_pinch_to_finger_power",
            max_distance_m=max_distance_m,
            min_distance_m=min_distance_m,
            saturation=saturation,
            falloff_exponent=falloff_exponent,
        )
        mapper_graph = mapper.connect(
            {PinchProximityToFingerPower.INPUT_HAND: hands.output(hands_output)}
        )
        powers_sel = mapper_graph.output(PinchProximityToFingerPower.OUTPUT_POWERS)
        sink_inputs[HapticSink.LEFT if side == "left" else HapticSink.RIGHT] = (
            powers_sel
        )
        monitoring[f"powers_{side}"] = powers_sel

    device = ManusHapticDevice()
    sink = HapticSink("haptic_sink_manus", device)
    sink_graph = sink.connect(sink_inputs)

    pipeline = OutputCombiner(
        {HapticSink.HEARTBEAT: sink_graph.output(HapticSink.HEARTBEAT), **monitoring}
    )
    return pipeline, monitoring


def _build_openxr_controller_pipeline(
    hands: HandsSource,
    controllers: ControllersSource,
    *,
    max_distance_m: float,
    min_distance_m: float,
    saturation: float,
    falloff_exponent: float,
    frequency_hz: float,
    duration_s: float,
):
    """Pinch-proximity -> max-across-fingers -> OpenXR controller rumble.

    Reuses ``controllers``' :class:`~isaacteleop.deviceio_trackers.ControllerTracker`
    instance for the haptic source so :class:`~isaacteleop.deviceio.DeviceIOSession`
    creates only one ``LiveControllerTrackerImpl``.

    Returns:
        Tuple of (OutputCombiner, monitoring) where monitoring exposes
        ``"powers_<side>"`` (FingerPowerVector) and ``"haptic_<side>"``
        (ControllerHapticPulse) per side for display.
    """
    sink_inputs: dict[str, Any] = {}
    monitoring: dict[str, Any] = {}

    for side, hands_output in (
        ("left", HandsSource.LEFT),
        ("right", HandsSource.RIGHT),
    ):
        mapper = PinchProximityToFingerPower(
            f"{side}_pinch_to_finger_power",
            max_distance_m=max_distance_m,
            min_distance_m=min_distance_m,
            saturation=saturation,
            falloff_exponent=falloff_exponent,
        )
        mapper_graph = mapper.connect(
            {PinchProximityToFingerPower.INPUT_HAND: hands.output(hands_output)}
        )
        monitoring[f"powers_{side}"] = mapper_graph.output(
            PinchProximityToFingerPower.OUTPUT_POWERS
        )

        collapser = FingerPowerToControllerPulse(
            f"{side}_finger_power_to_pulse",
            frequency_hz=frequency_hz,
            duration_s=duration_s,
        )
        collapser_graph = collapser.connect(
            {
                FingerPowerToControllerPulse.INPUT_POWERS: mapper_graph.output(
                    PinchProximityToFingerPower.OUTPUT_POWERS
                ),
            }
        )
        pulse_sel = collapser_graph.output(FingerPowerToControllerPulse.OUTPUT_PULSE)
        sink_inputs[HapticSink.LEFT if side == "left" else HapticSink.RIGHT] = pulse_sel
        monitoring[f"haptic_{side}"] = pulse_sel

    device = OpenXRControllerHapticDevice(sides=("left", "right"))
    sink = HapticSink("haptic_sink_openxr", device)
    sink_graph = sink.connect(sink_inputs)

    haptic_source = OpenXRControllerHapticSource.for_controllers_source(
        "_openxr_haptic_source", device, controllers
    )

    pipeline = OutputCombiner(
        {
            HapticSink.HEARTBEAT: sink_graph.output(HapticSink.HEARTBEAT),
            OpenXRControllerHapticSource.HEARTBEAT: haptic_source.output(
                OpenXRControllerHapticSource.HEARTBEAT
            ),
            **monitoring,
        }
    )
    return pipeline, monitoring


# ============================================================================
# Display helpers
# ============================================================================

_BAR_WIDTH = 6
_BAR_FILL = "█"
_BAR_EMPTY = "░"

# Short names for each finger column (Thumb first, Manus order).
_FINGER_LABELS = ["Th", "Ix", "Md", "Rg", "Pk"]


def _bar(value: float, width: int = _BAR_WIDTH) -> str:
    """Fixed-width ASCII progress bar for a value in [0, 1]."""
    filled = round(max(0.0, min(1.0, value)) * width)
    return _BAR_FILL * filled + _BAR_EMPTY * (width - filled)


def _read_powers(result: dict, key: str) -> list[float]:
    """Extract all 5 finger powers from a FingerPowerVector group."""
    group = result.get(key)
    if group is None or group.is_none:
        return [0.0] * NUM_HAPTIC_FINGERS
    arr = np.asarray(group[0], dtype=np.float32).ravel()
    return [float(arr[i]) if i < len(arr) else 0.0 for i in range(NUM_HAPTIC_FINGERS)]


def _read_haptic_amplitude(result: dict, key: str) -> float:
    """Extract the amplitude from a ControllerHapticPulse group."""
    group = result.get(key)
    if group is None or group.is_none:
        return 0.0
    return float(np.asarray(group[0])[ControllerHapticPulseField.AMPLITUDE])


def _render_finger_row(label: str, powers: list[float]) -> str:
    """Render one hand's per-finger bars as a compact inline string.

    Example:  ``L  Th ████░░ 0.65  Ix ░░░░░░ 0.00  Md ░░░░░░ 0.00  …``
    """
    cols = "  ".join(
        f"{_FINGER_LABELS[i]} {_bar(powers[i])} {powers[i]:.2f}"
        for i in range(NUM_HAPTIC_FINGERS)
    )
    return f"{label}  {cols}"


# ============================================================================
# CLI
# ============================================================================


def _positive_float(value: str) -> float:
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive float, got {value!r}")
    if n <= 0.0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {n}")
    return n


def _non_negative_float(value: str) -> float:
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}")
    if n < 0.0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _unit_float(value: str) -> float:
    n = _non_negative_float(value)
    if n > 1.0:
        raise argparse.ArgumentTypeError(f"must be in [0, 1], got {n}")
    return n


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hand-tracking pinch-proximity haptic feedback demo.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--device",
        choices=("manus", "openxr_controller"),
        default="manus",
        help=(
            "manus: per-finger Manus glove vibration (canonical use case). "
            "openxr_controller: collapse to single-channel motor rumble per hand "
            "(useful as a hardware smoke test without Manus)."
        ),
    )
    parser.add_argument(
        "--max-distance-m",
        type=_positive_float,
        default=0.10,
        help="Finger->thumb distance at which vibration starts (zero amplitude). Meters.",
    )
    parser.add_argument(
        "--min-distance-m",
        type=_non_negative_float,
        default=0.005,
        help="Finger->thumb distance at which vibration reaches the saturation amplitude. Meters.",
    )
    parser.add_argument(
        "--saturation",
        type=_unit_float,
        default=1.0,
        help="Maximum per-finger vibration amplitude in [0, 1].",
    )
    parser.add_argument(
        "--falloff-exponent",
        type=_positive_float,
        default=1.0,
        help=(
            "Shape of the distance->amplitude ramp. 1.0 = linear. <1 makes the response "
            "feel stronger as soon as you cross --max-distance-m; >1 makes only very "
            "close finger/thumb proximity register."
        ),
    )
    parser.add_argument(
        "--frequency-hz",
        type=_non_negative_float,
        default=0.0,
        help=(
            "OpenXR-only: pulse frequency. 0 -> XR_FREQUENCY_UNSPECIFIED. "
            "Ignored when --device manus (Manus has no frequency knob)."
        ),
    )
    parser.add_argument(
        "--duration-s",
        type=_non_negative_float,
        default=0.0,
        help=(
            "OpenXR-only: pulse duration per frame. 0 -> XR_MIN_HAPTIC_DURATION. "
            "Ignored when --device manus."
        ),
    )
    parser.add_argument(
        "--app-name",
        default="HandPinchHapticExample",
        help="App name for the TeleopSession (used for OpenXR action-set naming).",
    )
    parser.add_argument(
        "--fps",
        type=_positive_float,
        default=60.0,
        help="Demo loop target frame rate. The pipeline runs once per frame.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Suppress per-second status output. Useful on terminals that do "
            "not interpret ANSI cursor-move escapes (e.g. legacy cmd.exe; "
            "modern Windows Terminal handles them correctly)."
        ),
    )
    args = parser.parse_args()

    if args.min_distance_m >= args.max_distance_m:
        parser.error(
            f"--min-distance-m ({args.min_distance_m}) must be < --max-distance-m ({args.max_distance_m})"
        )

    hands = HandsSource("hands")

    if args.device == "manus":
        pipeline, monitoring = _build_manus_pipeline(
            hands,
            max_distance_m=args.max_distance_m,
            min_distance_m=args.min_distance_m,
            saturation=args.saturation,
            falloff_exponent=args.falloff_exponent,
        )
    else:
        # OpenXR mode reuses ControllersSource's tracker for the haptic source
        # (see _build_openxr_controller_pipeline for the rationale).
        controllers = ControllersSource("controllers")
        pipeline, monitoring = _build_openxr_controller_pipeline(
            hands,
            controllers,
            max_distance_m=args.max_distance_m,
            min_distance_m=args.min_distance_m,
            saturation=args.saturation,
            falloff_exponent=args.falloff_exponent,
            frequency_hz=args.frequency_hz,
            duration_s=args.duration_s,
        )

    config = TeleopSessionConfig(app_name=args.app_name, pipeline=pipeline)

    print("=" * 80)
    print("Hand-pinch Haptic Feedback Demo")
    print("=" * 80)
    print(f"Device           : {args.device}")
    print(
        f"Distance ramp    : {args.max_distance_m * 100:.1f} cm (start)  ->  "
        f"{args.min_distance_m * 100:.2f} cm (full)  "
        f"[exponent {args.falloff_exponent:.2f}, max amp {args.saturation:.2f}]"
    )
    if args.device == "openxr_controller":
        print(
            f"OpenXR pulse     : freq={args.frequency_hz:.1f} Hz "
            f"(0=runtime default), duration={args.duration_s:.3f} s (0=min)"
        )
    print()
    print("Columns: Th=Thumb  Ix=Index  Md=Middle  Rg=Ring  Pk=Pinky")
    print("Pinch any finger toward the thumb -- bars show vibration per finger.")
    if args.device == "openxr_controller":
        print("OXR: per-side rumble amplitude = max across all five fingers.")
    print("Press Ctrl+C to exit.")
    print()

    # Reserve two lines for the live per-hand display (one per hand) so the
    # header above stays visible while values scroll in-place.
    print()  # L hand placeholder
    print()  # R hand placeholder (or OXR haptic line)

    frame_period_s = 1.0 / args.fps

    with TeleopSession(config) as session:
        while True:
            result = session.step()

            if not args.quiet:
                powers_l = _read_powers(result, "powers_left")
                powers_r = _read_powers(result, "powers_right")

                row_l = _render_finger_row("L", powers_l)
                row_r = _render_finger_row("R", powers_r)

                if args.device == "openxr_controller":
                    amp_l = _read_haptic_amplitude(result, "haptic_left")
                    amp_r = _read_haptic_amplitude(result, "haptic_right")
                    oxr_line = (
                        f"   OXR  L rumble {_bar(amp_l, 8)} {amp_l:.2f}  "
                        f"R rumble {_bar(amp_r, 8)} {amp_r:.2f}  "
                        f"[frame {session.frame_count}]"
                    )
                    # Move up 3 lines, overwrite, move back down.
                    print(
                        f"\x1b[3A\r{row_l:<90}\n\r{row_r:<90}\n\r{oxr_line:<90}",
                        end="",
                        flush=True,
                    )
                else:
                    frame_tag = f"  [frame {session.frame_count}]"
                    # Move up 2 lines and overwrite.
                    print(
                        f"\x1b[2A\r{row_l:<90}\n\r{row_r + frame_tag:<90}",
                        end="",
                        flush=True,
                    )

            time.sleep(frame_period_s)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Newline after the in-place overwrite lines so the prompt is clean.
        print("\n\nExiting.")
        sys.exit(0)
