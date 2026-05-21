# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end haptic feedback demo for OpenXR motion controllers.

Builds a :class:`~isaacteleop.teleop_session_manager.TeleopSession` that drives
the haptic actuator on each controller through the full retargeting stack
introduced for tactile feedback in Isaac Teleop:

::

    ControllersSource (input)              OpenXRControllerHapticDevice
            |                                      ^   ^
            v                                      |   |
    TriggerToTactile  ->  TactileVectorToControllerPulse  ->  HapticSink
                                                              |
                                                              v
                                              OpenXRControllerHapticSource
                                                  (poll_tracker(session))

Default behaviour ("trigger" mode) closes a loop on the controllers
themselves: pulling the *left* trigger rumbles the *right* controller, and
vice versa. ``--mode sine`` ignores controller input and applies a smooth
0->1->0 sine envelope to both controllers so the haptic path can be
verified before any tactile data exists on the rig.

This example deliberately uses the **same** :class:`~isaacteleop.deviceio_trackers.ControllerTracker`
instance for both the input side
(:class:`~isaacteleop.retargeting_engine.deviceio_source_nodes.ControllersSource`)
and the haptic output side
(:class:`~isaacteleop.haptic_devices.openxr_controller.OpenXRControllerHapticSource`)
so the session only creates one ``LiveControllerTrackerImpl`` and there is
no contention on the underlying OpenXR action set.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

from isaacteleop.haptic_devices.openxr_controller import (
    OpenXRControllerHapticDevice,
    OpenXRControllerHapticSource,
)
from isaacteleop.retargeters.tactile_retargeters import TactileVectorToControllerPulse
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
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
    ControllerHapticPulseField,
    ControllerInput,
    ControllerInputIndex,
    TactileVector,
)
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig


# ============================================================================
# Demo retargeters
# ============================================================================


class TriggerToTactile(BaseRetargeter):
    """Demo retargeter: stream the controller trigger value as a TactileVector(1).

    Mirrors the shape of an :class:`isaaclab.sensors.ContactSensor`-driven
    fetch function (one scalar in [0, 1]) so the rest of the pipeline does
    not know whether the signal came from a sim contact or a real human
    finger on a controller trigger.
    """

    INPUT_CONTROLLER = "controller"
    OUTPUT_TACTILE = "tactile"

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_CONTROLLER: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_TACTILE: TactileVector(1)}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        controller = inputs[self.INPUT_CONTROLLER]
        if controller.is_none:
            outputs[self.OUTPUT_TACTILE][0] = np.zeros(1, dtype=np.float32)
            return
        trigger = float(controller[ControllerInputIndex.TRIGGER_VALUE])
        outputs[self.OUTPUT_TACTILE][0] = np.array([trigger], dtype=np.float32)


class SineWaveTactile(BaseRetargeter):
    """Demo retargeter: emit a TactileVector(1) following a half-rectified sine.

    Useful as a hardware smoke test -- it pulses haptics without requiring
    any human input on the controllers. ``period_s`` and ``peak`` are both
    construction-time scalars (no ParameterState needed; this is a demo
    knob, not a tuning knob).
    """

    OUTPUT_TACTILE = "tactile"

    def __init__(self, name: str, period_s: float = 2.0, peak: float = 1.0) -> None:
        if period_s <= 0.0:
            raise ValueError("SineWaveTactile period_s must be > 0")
        self._period_s = float(period_s)
        self._peak = float(peak)
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_TACTILE: TactileVector(1)}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        # Half-rectified sine: never negative (a negative haptic amplitude
        # would be silently clamped downstream but it is clearer to do it here).
        t = context.graph_time.real_time_ns / 1.0e9
        phase = (2.0 * math.pi * t) / self._period_s
        amplitude = self._peak * max(0.0, math.sin(phase))
        outputs[self.OUTPUT_TACTILE][0] = np.array([amplitude], dtype=np.float32)


# ============================================================================
# Pipeline builders for each demo mode
# ============================================================================


def _build_trigger_pipeline(
    controllers: ControllersSource,
    sink: HapticSink,
    cross_hand: bool,
    *,
    saturation: float,
    frequency_hz: float,
    duration_s: float,
):
    """Wire the cross-hand (or same-hand) trigger -> rumble loop.

    Each side gets its own :class:`TriggerToTactile` + per-pulse mapper; the
    sink consumes one ``ControllerHapticPulse`` per side.

    Returns:
        Tuple of (sink_graph, monitoring) where monitoring is a dict of
        ``OutputSelector``s keyed ``"trigger_<side>"`` and ``"haptic_<side>"``
        so the main ``OutputCombiner`` can expose them for printing.
    """
    sides = ("left", "right")
    trigger_selectors: dict[str, object] = {}
    pulse_selectors: dict[str, object] = {}

    for side in sides:
        trigger = TriggerToTactile(f"{side}_trigger")
        trigger_graph = trigger.connect(
            {
                TriggerToTactile.INPUT_CONTROLLER: controllers.output(
                    ControllersSource.LEFT
                    if side == "left"
                    else ControllersSource.RIGHT
                ),
            }
        )
        trigger_selectors[side] = trigger_graph.output(TriggerToTactile.OUTPUT_TACTILE)

        mapper = TactileVectorToControllerPulse(
            f"{side}_trigger_to_pulse",
            num_taxels=1,
            saturation=saturation,
            frequency_hz=frequency_hz,
            duration_s=duration_s,
        )
        mapper_graph = mapper.connect(
            {
                TactileVectorToControllerPulse.INPUT_TACTILE: trigger_graph.output(
                    TriggerToTactile.OUTPUT_TACTILE
                ),
            }
        )
        pulse_selectors[side] = mapper_graph.output(
            TactileVectorToControllerPulse.OUTPUT_PULSE
        )

    if cross_hand:
        # Left trigger -> right controller rumble (and vice versa). Closes a
        # nice "feel what your other hand is doing" loop on a single user.
        sink_inputs = {
            HapticSink.LEFT: pulse_selectors["right"],
            HapticSink.RIGHT: pulse_selectors["left"],
        }
    else:
        sink_inputs = {
            HapticSink.LEFT: pulse_selectors["left"],
            HapticSink.RIGHT: pulse_selectors["right"],
        }

    monitoring = {
        "trigger_left": trigger_selectors["left"],
        "trigger_right": trigger_selectors["right"],
        "haptic_left": pulse_selectors["left"],
        "haptic_right": pulse_selectors["right"],
    }
    return sink.connect(sink_inputs), monitoring


def _build_sine_pipeline(
    sink: HapticSink,
    *,
    period_s: float,
    saturation: float,
    frequency_hz: float,
    duration_s: float,
):
    """Wire a synchronized sine envelope to both sides (no controller input).

    Returns:
        Tuple of (sink_graph, monitoring) where monitoring exposes the raw
        sine amplitude under ``"sine_amplitude"`` for printing.
    """
    tactile = SineWaveTactile("sine_tactile", period_s=period_s, peak=1.0)
    mapper = TactileVectorToControllerPulse(
        "sine_to_pulse",
        num_taxels=1,
        saturation=saturation,
        frequency_hz=frequency_hz,
        duration_s=duration_s,
    )
    tactile_selector = tactile.output(SineWaveTactile.OUTPUT_TACTILE)
    mapper_graph = mapper.connect(
        {TactileVectorToControllerPulse.INPUT_TACTILE: tactile_selector}
    )
    pulse_selector = mapper_graph.output(TactileVectorToControllerPulse.OUTPUT_PULSE)
    monitoring = {
        "sine_amplitude": tactile_selector,
        "haptic_left": pulse_selector,
        "haptic_right": pulse_selector,
    }
    return sink.connect(
        {HapticSink.LEFT: pulse_selector, HapticSink.RIGHT: pulse_selector}
    ), monitoring


# ============================================================================
# Display helpers
# ============================================================================

_BAR_WIDTH = 10
_BAR_FILL = "█"
_BAR_EMPTY = "░"


def _bar(value: float, width: int = _BAR_WIDTH) -> str:
    """Render a fixed-width ASCII progress bar for a value in [0, 1]."""
    filled = round(max(0.0, min(1.0, value)) * width)
    return _BAR_FILL * filled + _BAR_EMPTY * (width - filled)


def _read_tactile(result: dict, key: str) -> float:
    """Extract the first scalar from a TactileVector(1) group in the result dict."""
    group = result.get(key)
    if group is None or group.is_none:
        return 0.0
    return float(np.asarray(group[0]).ravel()[0])


def _read_haptic_amplitude(result: dict, key: str) -> float:
    """Extract the amplitude from a ControllerHapticPulse group in the result dict."""
    group = result.get(key)
    if group is None or group.is_none:
        return 0.0
    return float(np.asarray(group[0])[ControllerHapticPulseField.AMPLITUDE])


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
        description="OpenXR controller haptic feedback demo.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=("trigger", "sine"),
        default="trigger",
        help=(
            "trigger: pull a trigger to rumble a controller (closed-loop on the user). "
            "sine: emit a smooth sine envelope on both controllers (no input needed)."
        ),
    )
    parser.add_argument(
        "--same-hand",
        action="store_true",
        help="trigger mode only: rumble the same-side controller instead of the cross-hand controller.",
    )
    parser.add_argument(
        "--sine-period",
        type=_positive_float,
        default=2.0,
        help="sine mode only: full-cycle period of the rumble envelope, in seconds.",
    )
    parser.add_argument(
        "--saturation",
        type=_unit_float,
        default=1.0,
        help="Upper clamp on the haptic pulse amplitude in [0, 1].",
    )
    parser.add_argument(
        "--frequency-hz",
        type=_non_negative_float,
        default=0.0,
        help="OpenXR pulse frequency. 0 -> XR_FREQUENCY_UNSPECIFIED (runtime picks).",
    )
    parser.add_argument(
        "--duration-s",
        type=_non_negative_float,
        default=0.0,
        help="OpenXR pulse duration per frame. 0 -> XR_MIN_HAPTIC_DURATION (shortest the runtime supports).",
    )
    parser.add_argument(
        "--app-name",
        default="OpenXRHapticFeedbackExample",
        help="App name for the TeleopSession (used for OpenXR action-set naming).",
    )
    parser.add_argument(
        "--fps",
        type=_positive_float,
        default=60.0,
        help="Demo loop target frame rate. The pipeline runs once per frame.",
    )
    args = parser.parse_args()

    # --------------------------------------------------------------
    # Sources & device adapter
    # --------------------------------------------------------------
    controllers = ControllersSource("controllers")
    device = OpenXRControllerHapticDevice(sides=("left", "right"))
    sink = HapticSink("haptic_sink", device)

    # Reuse the controller tracker from ControllersSource so DeviceIOSession
    # only creates one LiveControllerTrackerImpl (the impl owns the OpenXR
    # action set, and two impls would race on the same actions). The
    # `for_controllers_source` helper makes the sharing explicit so the two
    # sources cannot accidentally diverge on the tracker handle.
    haptic_source = OpenXRControllerHapticSource.for_controllers_source(
        "_openxr_haptic_source", device, controllers
    )

    # --------------------------------------------------------------
    # Per-mode wiring
    # --------------------------------------------------------------
    if args.mode == "trigger":
        sink_graph, monitoring = _build_trigger_pipeline(
            controllers,
            sink,
            cross_hand=not args.same_hand,
            saturation=args.saturation,
            frequency_hz=args.frequency_hz,
            duration_s=args.duration_s,
        )
    else:
        sink_graph, monitoring = _build_sine_pipeline(
            sink,
            period_s=args.sine_period,
            saturation=args.saturation,
            frequency_hz=args.frequency_hz,
            duration_s=args.duration_s,
        )

    # OutputCombiner only walks back from declared outputs; the heartbeats on
    # the sink and the haptic source make both reachable so the session
    # auto-discovers them as leaves and drains the queue every frame.
    # Monitoring outputs are also included so the main loop can read them back
    # from session.step() without any extra retargeters.
    pipeline = OutputCombiner(
        {
            HapticSink.HEARTBEAT: sink_graph.output(HapticSink.HEARTBEAT),
            OpenXRControllerHapticSource.HEARTBEAT: haptic_source.output(
                OpenXRControllerHapticSource.HEARTBEAT
            ),
            **monitoring,
        }
    )

    # --------------------------------------------------------------
    # Run
    # --------------------------------------------------------------
    config = TeleopSessionConfig(app_name=args.app_name, pipeline=pipeline)

    print("=" * 80)
    print("OpenXR Controller Haptic Feedback Demo")
    print("=" * 80)
    if args.mode == "trigger":
        if args.same_hand:
            print(
                "Mode: trigger (same-hand) -- each trigger rumbles its own controller."
            )
        else:
            print(
                "Mode: trigger (cross-hand) -- LEFT trigger rumbles RIGHT controller, "
                "and vice versa."
            )
    else:
        print(
            f"Mode: sine -- both controllers rumble on a {args.sine_period:.2f}s sine envelope."
        )
    print(
        f"Saturation={args.saturation:.2f}, frequency_hz={args.frequency_hz:.2f} "
        f"(0=runtime default), duration_s={args.duration_s:.3f} (0=min)"
    )
    print("Press Ctrl+C to exit.")
    print()

    frame_period_s = 1.0 / args.fps
    cross_hand = args.mode == "trigger" and not args.same_hand

    with TeleopSession(config) as session:
        while True:
            result = session.step()

            # Print every frame so values scroll in real time. The terminal
            # cursor overwrites the previous line using \r so the output stays
            # in place rather than scrolling. Use --fps to control how fast
            # values update.
            if args.mode == "trigger":
                trig_l = _read_tactile(result, "trigger_left")
                trig_r = _read_tactile(result, "trigger_right")
                # In cross-hand mode the left trigger drives the right haptic
                # and vice versa; label accordingly so the arrow makes sense.
                hap_l = _read_haptic_amplitude(result, "haptic_left")
                hap_r = _read_haptic_amplitude(result, "haptic_right")
                if cross_hand:
                    line = (
                        f"L trig {_bar(trig_l)} {trig_l:.2f} -> R haptic {_bar(hap_r)} {hap_r:.2f}  |  "
                        f"R trig {_bar(trig_r)} {trig_r:.2f} -> L haptic {_bar(hap_l)} {hap_l:.2f}  "
                        f"[frame {session.frame_count}]"
                    )
                else:
                    line = (
                        f"L trig {_bar(trig_l)} {trig_l:.2f} -> L haptic {_bar(hap_l)} {hap_l:.2f}  |  "
                        f"R trig {_bar(trig_r)} {trig_r:.2f} -> R haptic {_bar(hap_r)} {hap_r:.2f}  "
                        f"[frame {session.frame_count}]"
                    )
            else:
                amp = _read_tactile(result, "sine_amplitude")
                hap_l = _read_haptic_amplitude(result, "haptic_left")
                hap_r = _read_haptic_amplitude(result, "haptic_right")
                line = (
                    f"sine {_bar(amp)} {amp:.2f} -> "
                    f"L haptic {_bar(hap_l)} {hap_l:.2f}  "
                    f"R haptic {_bar(hap_r)} {hap_r:.2f}  "
                    f"[frame {session.frame_count}]"
                )

            # Pad to terminal width so partial overwrites don't leave stale chars.
            print(f"\r{line:<100}", end="", flush=True)

            time.sleep(frame_period_s)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Newline after the \r-overwritten status line so the shell prompt
        # appears on a clean line.
        print("\nExiting.")
        sys.exit(0)
