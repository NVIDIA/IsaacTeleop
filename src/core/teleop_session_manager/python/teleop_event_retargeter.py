# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TeleopEventRetargeter — multi-channel event retargeter for teleop session control.

Takes up to 6 bool inputs (start, stop, pause/resume, calibrate start/end, reset)
and produces three event channel outputs (run_events, calibration_events, reset_events).

Internal state machine:
  Run state:           STOPPED | RUNNING | PAUSED
  Calibration active:  bool (orthogonal to run state)

Events fire on rising edges with per-input debounce. All inputs except
start_input and calibrate_end_input are Optional — omitting them permanently
disables the corresponding feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict

from isaacteleop.retargeting_engine.interface.base_retargeter import BaseRetargeter
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.teleop_events import (
    TeleopCalibrationEvent,
    TeleopResetEvent,
    TeleopRunEvent,
    calibration_event_channel,
    reset_event_channel,
    run_event_channel,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types import BoolValue


# ============================================================================
# Internal state enum (private to this module)
# ============================================================================


class _RunState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


# ============================================================================
# Config
# ============================================================================


@dataclass
class TeleopEventRetargeterConfig:
    """Configuration for TeleopEventRetargeter.

    Attributes:
        debounce_ms: Minimum time in milliseconds between successive firings of
                     the same input. Prevents accidental double-fires when a
                     button is held. Applied per-input independently.
    """

    debounce_ms: float = 300.0


# ============================================================================
# TeleopEventRetargeter
# ============================================================================


class TeleopEventRetargeter(BaseRetargeter):
    """Multi-channel event retargeter for teleop session lifecycle control.

    Consumes up to 6 boolean inputs and produces 3 event channel outputs.
    Each output channel is a TensorGroupType derived from its event enum —
    one BoolType slot per enum member, True when that event fired this frame.

    Input spec:
        Required:
            start_input          (BoolValue) — rising edge → run.START, STOPPED→RUNNING
            calibrate_end_input  (BoolValue) — rising edge → cal.END (when calibrating)

        Optional (omit to disable the feature):
            stop_input           (BoolValue) — rising edge → run.STOP, any→STOPPED
            pause_resume_input   (BoolValue) — rising edge → run.PAUSE (RUNNING) or run.RESUME (PAUSED)
            calibrate_start_input(BoolValue) — rising edge → cal.START (RUNNING/PAUSED)
            reset_input          (BoolValue) — rising edge → reset.RESET + forced stop

    Output spec:
        run_events         — TensorGroupType from TeleopRunEvent
        calibration_events — TensorGroupType from TeleopCalibrationEvent
        reset_events       — TensorGroupType from TeleopResetEvent

    Priority (highest first): reset > stop > start > pause_resume > calibrate_start > calibrate_end

    Example::

        retargeter = TeleopEventRetargeter("events", TeleopEventRetargeterConfig())
        pipeline = retargeter.connect({
            "start_input":           start_selector.output("bool_value"),
            "calibrate_end_input":   cal_end_selector.output("bool_value"),
            "stop_input":            stop_selector.output("bool_value"),
            "pause_resume_input":    pause_selector.output("bool_value"),
            "calibrate_start_input": cal_start_selector.output("bool_value"),
            "reset_input":           reset_selector.output("bool_value"),
        })
    """

    # Input name constants
    _START = "start_input"
    _STOP = "stop_input"
    _PAUSE_RESUME = "pause_resume_input"
    _CAL_START = "calibrate_start_input"
    _CAL_END = "calibrate_end_input"
    _RESET = "reset_input"

    _ALL_INPUTS = [_START, _STOP, _PAUSE_RESUME, _CAL_START, _CAL_END, _RESET]

    def __init__(self, name: str, config: TeleopEventRetargeterConfig) -> None:
        """Initialize TeleopEventRetargeter.

        Args:
            name:   Unique name for this retargeter node.
            config: Configuration (debounce_ms).
        """
        self._config = config
        self._run_state: _RunState = _RunState.STOPPED
        self._calibration_active: bool = False

        # Per-input rising-edge tracking
        self._prev: Dict[str, bool] = {k: False for k in self._ALL_INPUTS}
        # Per-input last-fire timestamp in nanoseconds (0 = never fired)
        self._last_fire_ns: Dict[str, int] = {k: 0 for k in self._ALL_INPUTS}

        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {
            # Required
            self._START: BoolValue(),
            self._CAL_END: BoolValue(),
            # Optional — omitting disables that feature
            self._STOP: OptionalType(BoolValue()),
            self._PAUSE_RESUME: OptionalType(BoolValue()),
            self._CAL_START: OptionalType(BoolValue()),
            self._RESET: OptionalType(BoolValue()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "run_events": run_event_channel(),
            "calibration_events": calibration_event_channel(),
            "reset_events": reset_event_channel(),
        }

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        now_ns = context.graph_time.real_time_ns
        debounce_ns = int(self._config.debounce_ms * 1_000_000)

        # ------------------------------------------------------------------ #
        # Read all inputs — rising edge with optional debounce                 #
        # ------------------------------------------------------------------ #
        def _read_pressed(input_name: str) -> bool:
            tg = inputs.get(input_name)
            return False if (tg is None or tg.is_none) else bool(tg[0])

        def _rising(input_name: str, debounce: bool = True) -> bool:
            """Return True on a rising edge; optionally apply debounce.

            stop_input skips debounce — every new press fires immediately so a
            stop is never accidentally swallowed by the debounce window.
            """
            pressed = _read_pressed(input_name)
            prev = self._prev[input_name]
            self._prev[input_name] = pressed

            if not pressed or prev:
                return False
            if debounce and now_ns - self._last_fire_ns[input_name] < debounce_ns:
                return False
            self._last_fire_ns[input_name] = now_ns
            return True

        reset_edge = _rising(self._RESET)
        stop_edge = _rising(self._STOP, debounce=False)  # stop is safety-critical
        start_edge = _rising(self._START)
        pause_resume_edge = _rising(self._PAUSE_RESUME)
        cal_start_edge = _rising(self._CAL_START)
        cal_end_edge = _rising(self._CAL_END)

        # ------------------------------------------------------------------ #
        # Collect fired events (sets, then write to outputs at the end)        #
        # ------------------------------------------------------------------ #
        fired_run: set = set()
        fired_cal: set = set()
        fired_reset: set = set()

        def _force_stop() -> None:
            """Stop running/paused state and clear calibration."""
            if self._run_state in (_RunState.RUNNING, _RunState.PAUSED):
                fired_run.add(TeleopRunEvent.STOP)
                self._run_state = _RunState.STOPPED
            if self._calibration_active:
                fired_cal.add(TeleopCalibrationEvent.CALIBRATION_END)
                self._calibration_active = False

        # Priority: reset > stop > start > pause_resume > cal_start > cal_end

        if reset_edge:
            fired_reset.add(TeleopResetEvent.RESET)
            _force_stop()

        elif stop_edge:
            _force_stop()

        else:
            if start_edge and self._run_state == _RunState.STOPPED:
                fired_run.add(TeleopRunEvent.START)
                self._run_state = _RunState.RUNNING

            if pause_resume_edge:
                if self._run_state == _RunState.RUNNING:
                    fired_run.add(TeleopRunEvent.PAUSE)
                    self._run_state = _RunState.PAUSED
                elif self._run_state == _RunState.PAUSED:
                    fired_run.add(TeleopRunEvent.RESUME)
                    self._run_state = _RunState.RUNNING

            if cal_start_edge:
                if self._run_state in (_RunState.RUNNING, _RunState.PAUSED):
                    if not self._calibration_active:
                        fired_cal.add(TeleopCalibrationEvent.CALIBRATION_START)
                        self._calibration_active = True

            if cal_end_edge and self._calibration_active:
                fired_cal.add(TeleopCalibrationEvent.CALIBRATION_END)
                self._calibration_active = False

        # ------------------------------------------------------------------ #
        # Write fired events to output tensor groups                           #
        # ------------------------------------------------------------------ #
        for idx, event in enumerate(TeleopRunEvent):
            outputs["run_events"][idx] = event in fired_run

        for idx, event in enumerate(TeleopCalibrationEvent):
            outputs["calibration_events"][idx] = event in fired_cal

        for idx, event in enumerate(TeleopResetEvent):
            outputs["reset_events"][idx] = event in fired_reset
