# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for TeleopEventRetargeter.

Covers:
 - State transitions (STOPPED → RUNNING → PAUSED → STOPPED)
 - Calibration lifecycle (start / end)
 - Reset event (fires RESET + forces stop + ends calibration)
 - Rising-edge detection (held button does not re-fire)
 - Debounce (rapid re-press within window is ignored; stop bypasses debounce)
 - Priority ordering (reset > stop > start > pause_resume > cal_start > cal_end)
 - Optional inputs (absent optional inputs are treated as permanently False)
 - Guard conditions (e.g. start only from STOPPED, cal_start only when RUNNING/PAUSED)
"""

import pytest

from isaacteleop.retargeting_engine.interface import TensorGroup, TensorGroupType
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    GraphTime,
)
from isaacteleop.retargeting_engine.interface.teleop_events import (
    TeleopCalibrationEvent,
    TeleopResetEvent,
    TeleopRunEvent,
)
from isaacteleop.retargeting_engine.tensor_types import BoolValue
from isaacteleop.teleop_session_manager import (
    TeleopEventRetargeter,
    TeleopEventRetargeterConfig,
)


# ============================================================================
# Helpers
# ============================================================================


def _bool_tg(value: bool) -> TensorGroup:
    """Create a BoolValue TensorGroup with the given boolean value."""
    tg = TensorGroup(BoolValue())
    tg[0] = value
    return tg


def _make_context(real_time_ns: int = 0) -> ComputeContext:
    """Create a ComputeContext at the given timestamp (nanoseconds)."""
    return ComputeContext(graph_time=GraphTime(sim_time_ns=real_time_ns, real_time_ns=real_time_ns))


def _make_retargeter(debounce_ms: float = 0.0) -> TeleopEventRetargeter:
    """Create a TeleopEventRetargeter with zero debounce for deterministic tests."""
    return TeleopEventRetargeter("ter", TeleopEventRetargeterConfig(debounce_ms=debounce_ms))


class RetargeterHarness:
    """Thin wrapper for driving TeleopEventRetargeter step by step.

    Maintains a mutable input dict and a timestamp counter. Callers set
    button state with press()/release() and advance the clock by calling
    step(), which returns the output dict.
    """

    def __init__(self, debounce_ms: float = 0.0):
        self.ter = _make_retargeter(debounce_ms=debounce_ms)
        self._buttons: dict[str, bool] = {
            "start_input": False,
            "calibrate_end_input": False,
            "stop_input": False,
            "pause_resume_input": False,
            "calibrate_start_input": False,
            "reset_input": False,
        }
        self._time_ns: int = 0

    def press(self, *names: str) -> "RetargeterHarness":
        for name in names:
            self._buttons[name] = True
        return self

    def release(self, *names: str) -> "RetargeterHarness":
        for name in names:
            self._buttons[name] = False
        return self

    def advance_time(self, ms: float) -> "RetargeterHarness":
        self._time_ns += int(ms * 1_000_000)
        return self

    def step(self) -> dict:
        inputs = {name: _bool_tg(val) for name, val in self._buttons.items()}
        ctx = _make_context(self._time_ns)
        return self.ter(inputs, ctx)

    def run_events(self) -> frozenset:
        out = self.step()
        return frozenset(e for i, e in enumerate(TeleopRunEvent) if out["run_events"][i])

    def cal_events(self) -> frozenset:
        out = self.step()
        return frozenset(e for i, e in enumerate(TeleopCalibrationEvent) if out["calibration_events"][i])

    def reset_events(self) -> frozenset:
        out = self.step()
        return frozenset(e for i, e in enumerate(TeleopResetEvent) if out["reset_events"][i])

    def step_events(self) -> tuple[frozenset, frozenset, frozenset]:
        """Return (run_events, cal_events, reset_events) for one step."""
        out = self.step()
        run = frozenset(e for i, e in enumerate(TeleopRunEvent) if out["run_events"][i])
        cal = frozenset(e for i, e in enumerate(TeleopCalibrationEvent) if out["calibration_events"][i])
        rst = frozenset(e for i, e in enumerate(TeleopResetEvent) if out["reset_events"][i])
        return run, cal, rst

    def idle(self) -> "RetargeterHarness":
        """Advance one step with all buttons released (no rising edges)."""
        self.release("start_input", "calibrate_end_input", "stop_input",
                     "pause_resume_input", "calibrate_start_input", "reset_input")
        self.step()
        return self


# ============================================================================
# Rising-edge and held-button behaviour
# ============================================================================


class TestRisingEdge:
    def test_held_start_does_not_refire(self):
        h = RetargeterHarness()
        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START in run

        # Held for two more frames — no new START
        run2, _, _ = h.step_events()
        run3, _, _ = h.step_events()
        assert TeleopRunEvent.START not in run2
        assert TeleopRunEvent.START not in run3

    def test_release_and_repress_fires_again(self):
        h = RetargeterHarness()
        h.press("start_input").step()   # START fires, now RUNNING
        h.release("start_input").step() # released, no event
        h.press("stop_input").step()    # STOP → back to STOPPED
        h.release("stop_input").step()

        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START in run

    def test_idle_step_produces_no_events(self):
        h = RetargeterHarness()
        run, cal, rst = h.step_events()
        assert not run
        assert not cal
        assert not rst


# ============================================================================
# Run state machine
# ============================================================================


class TestRunStateMachine:
    def test_start_transitions_stopped_to_running(self):
        h = RetargeterHarness()
        h.press("start_input")
        run, _, _ = h.step_events()
        assert run == {TeleopRunEvent.START}

    def test_start_ignored_when_already_running(self):
        h = RetargeterHarness()
        # First start
        h.press("start_input").step()
        h.release("start_input").step()
        # Try to start again while already RUNNING
        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START not in run

    def test_stop_transitions_running_to_stopped(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("stop_input")
        run, _, _ = h.step_events()
        assert run == {TeleopRunEvent.STOP}

    def test_stop_ignored_when_already_stopped(self):
        h = RetargeterHarness()
        h.press("stop_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.STOP not in run

    def test_pause_from_running(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("pause_resume_input")
        run, _, _ = h.step_events()
        assert run == {TeleopRunEvent.PAUSE}

    def test_resume_from_paused(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("pause_resume_input").step()
        h.release("pause_resume_input").step()

        h.press("pause_resume_input")
        run, _, _ = h.step_events()
        assert run == {TeleopRunEvent.RESUME}

    def test_stop_from_paused(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("pause_resume_input").step()
        h.release("pause_resume_input").step()

        h.press("stop_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.STOP in run

    def test_pause_ignored_when_stopped(self):
        h = RetargeterHarness()
        h.press("pause_resume_input")
        run, _, _ = h.step_events()
        assert not run


# ============================================================================
# Calibration lifecycle
# ============================================================================


class TestCalibration:
    def test_cal_start_while_running(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("calibrate_start_input")
        _, cal, _ = h.step_events()
        assert cal == {TeleopCalibrationEvent.CALIBRATION_START}

    def test_cal_start_while_paused(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("pause_resume_input").step()
        h.release("pause_resume_input").step()

        h.press("calibrate_start_input")
        _, cal, _ = h.step_events()
        assert cal == {TeleopCalibrationEvent.CALIBRATION_START}

    def test_cal_start_ignored_when_stopped(self):
        h = RetargeterHarness()
        h.press("calibrate_start_input")
        _, cal, _ = h.step_events()
        assert not cal

    def test_cal_start_ignored_when_already_calibrating(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("calibrate_start_input").step()
        h.release("calibrate_start_input").step()

        # Second cal_start while already calibrating
        h.press("calibrate_start_input")
        _, cal, _ = h.step_events()
        assert not cal

    def test_cal_end_fires_when_calibrating(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("calibrate_start_input").step()
        h.release("calibrate_start_input").step()

        h.press("calibrate_end_input")
        _, cal, _ = h.step_events()
        assert cal == {TeleopCalibrationEvent.CALIBRATION_END}

    def test_cal_end_ignored_when_not_calibrating(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("calibrate_end_input")
        _, cal, _ = h.step_events()
        assert not cal

    def test_stop_ends_active_calibration(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("calibrate_start_input").step()
        h.release("calibrate_start_input").step()

        h.press("stop_input")
        run, cal, _ = h.step_events()
        assert TeleopRunEvent.STOP in run
        assert TeleopCalibrationEvent.CALIBRATION_END in cal


# ============================================================================
# Reset event
# ============================================================================


class TestReset:
    def test_reset_fires_from_stopped(self):
        h = RetargeterHarness()
        h.press("reset_input")
        run, cal, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst
        assert not run
        assert not cal

    def test_reset_stops_running_session(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("reset_input")
        run, _, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst
        assert TeleopRunEvent.STOP in run

    def test_reset_stops_paused_session(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("pause_resume_input").step()
        h.release("pause_resume_input").step()

        h.press("reset_input")
        run, _, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst
        assert TeleopRunEvent.STOP in run

    def test_reset_ends_active_calibration(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("calibrate_start_input").step()
        h.release("calibrate_start_input").step()

        h.press("reset_input")
        run, cal, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst
        assert TeleopRunEvent.STOP in run
        assert TeleopCalibrationEvent.CALIBRATION_END in cal

    def test_after_reset_can_start_again(self):
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("reset_input").step()
        h.release("reset_input").step()

        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START in run


# ============================================================================
# Priority ordering
# ============================================================================


class TestPriority:
    def test_reset_overrides_stop(self):
        """When reset and stop fire simultaneously, reset takes priority."""
        h = RetargeterHarness()
        h.press("start_input").step()
        h.release("start_input").step()

        h.press("reset_input", "stop_input")
        run, _, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst
        # STOP appears because _force_stop() fires it inside reset handler too
        assert TeleopRunEvent.STOP in run

    def test_stop_overrides_start(self):
        """When stop and start fire simultaneously, stop takes priority."""
        h = RetargeterHarness()
        h.press("start_input").step()      # start → RUNNING
        h.release("start_input").step()
        h.press("stop_input").step()       # stop → STOPPED
        h.release("stop_input").step()

        # Now STOPPED: press start and stop simultaneously
        h.press("start_input", "stop_input")
        run, _, _ = h.step_events()
        # stop gate fires (STOPPED→STOPPED, no STOP event since already stopped),
        # start is suppressed by the elif chain
        assert TeleopRunEvent.START not in run

    def test_reset_overrides_start_and_stop(self):
        h = RetargeterHarness()
        h.press("reset_input", "start_input", "stop_input")
        _, _, rst = h.step_events()
        assert TeleopResetEvent.RESET in rst


# ============================================================================
# Debounce
# ============================================================================


class TestDebounce:
    def test_debounced_input_ignored_within_window(self):
        """A rapid re-press of start (non-stop) within debounce_ms is ignored."""
        debounce_ms = 300.0
        h = RetargeterHarness(debounce_ms=debounce_ms)

        # First press → START
        h.press("start_input").step()
        h.release("start_input").step()

        # stop to reset to STOPPED
        h.press("stop_input").step()
        h.release("stop_input").step()

        # Re-press start within debounce window (time hasn't advanced enough)
        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START not in run

    def test_debounced_input_fires_after_window(self):
        debounce_ms = 300.0
        h = RetargeterHarness(debounce_ms=debounce_ms)

        # First press → START fires, advance past debounce window
        h.press("start_input").step()
        h.release("start_input").step()
        h.press("stop_input").step()
        h.release("stop_input").step()

        h.advance_time(debounce_ms + 1)

        h.press("start_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.START in run

    def test_stop_bypasses_debounce(self):
        """stop_input fires immediately regardless of the debounce window."""
        debounce_ms = 300.0
        h = RetargeterHarness(debounce_ms=debounce_ms)

        # Start the session
        h.press("start_input").step()
        h.release("start_input").step()

        # First stop
        h.press("stop_input").step()
        h.release("stop_input").step()

        # Restart (advance time past debounce)
        h.advance_time(debounce_ms + 1)
        h.press("start_input").step()
        h.release("start_input").step()

        # Second stop — immediately, no time advance
        h.press("stop_input")
        run, _, _ = h.step_events()
        assert TeleopRunEvent.STOP in run


# ============================================================================
# Optional inputs (absent = permanently False)
# ============================================================================


class TestOptionalInputs:
    def test_absent_stop_cannot_stop(self):
        """When stop_input is not provided, the session can never be stopped via stop."""
        ter = _make_retargeter()
        ctx = _make_context()

        # Only provide the two required inputs
        inputs = {
            "start_input": _bool_tg(True),
            "calibrate_end_input": _bool_tg(False),
        }
        out = ter(inputs, ctx)
        run = frozenset(e for i, e in enumerate(TeleopRunEvent) if out["run_events"][i])
        assert TeleopRunEvent.START in run

        # Stop not wired — press stop conceptually does nothing (not in inputs)
        inputs2 = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
        }
        out2 = ter(inputs2, ctx)
        run2 = frozenset(e for i, e in enumerate(TeleopRunEvent) if out2["run_events"][i])
        assert TeleopRunEvent.STOP not in run2

    def test_absent_reset_produces_no_reset_events(self):
        ter = _make_retargeter()
        ctx = _make_context()

        inputs = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
            # reset_input intentionally absent
        }
        out = ter(inputs, ctx)
        rst = frozenset(e for i, e in enumerate(TeleopResetEvent) if out["reset_events"][i])
        assert not rst

    def test_absent_pause_resume_prevents_pause(self):
        """Without pause_resume_input wired, PAUSED state is unreachable."""
        ter = _make_retargeter()
        ctx = _make_context()

        # Start
        ter({"start_input": _bool_tg(True), "calibrate_end_input": _bool_tg(False)}, ctx)

        # Try to pause (only required inputs in dict)
        out = ter({"start_input": _bool_tg(False), "calibrate_end_input": _bool_tg(False)}, ctx)
        run = frozenset(e for i, e in enumerate(TeleopRunEvent) if out["run_events"][i])
        assert TeleopRunEvent.PAUSE not in run


# ============================================================================
# Output channel structure
# ============================================================================


class TestOutputStructure:
    def test_all_three_channels_present(self):
        ter = _make_retargeter()
        ctx = _make_context()
        inputs = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
        }
        out = ter(inputs, ctx)
        assert "run_events" in out
        assert "calibration_events" in out
        assert "reset_events" in out

    def test_run_events_has_correct_slot_count(self):
        ter = _make_retargeter()
        ctx = _make_context()
        inputs = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
        }
        out = ter(inputs, ctx)
        # One slot per TeleopRunEvent member
        assert len(out["run_events"].group_type.types) == len(TeleopRunEvent)

    def test_calibration_events_has_correct_slot_count(self):
        ter = _make_retargeter()
        ctx = _make_context()
        inputs = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
        }
        out = ter(inputs, ctx)
        assert len(out["calibration_events"].group_type.types) == len(TeleopCalibrationEvent)

    def test_reset_events_has_correct_slot_count(self):
        ter = _make_retargeter()
        ctx = _make_context()
        inputs = {
            "start_input": _bool_tg(False),
            "calibrate_end_input": _bool_tg(False),
        }
        out = ter(inputs, ctx)
        assert len(out["reset_events"].group_type.types) == len(TeleopResetEvent)
