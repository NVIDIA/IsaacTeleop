# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``isaacteleop.haptic_devices.openxr_controller``.

The OpenXR controller adapter is split into a sink-time
``OpenXRControllerHapticDevice`` (queues per-side pulses without a session in
scope) and a session-aware ``OpenXRControllerHapticSource`` that drains the
queue inside ``poll_tracker(session)``. We need to lock down:

* Queue semantics (latest-wins coalescing, per-side independence, drain-clears).
* Shape validation on ``apply()``.
* Source forwards drained pulses to ``ControllerTracker.apply_haptic_feedback``
  with the right argument shape.
* Source swallows tracker exceptions and only logs once per side.
* ``for_controllers_source`` shares the underlying tracker handle.
"""

from typing import List, Tuple

import numpy as np
import pytest

from isaacteleop.haptic_devices.openxr_controller import (
    OpenXRControllerHapticDevice,
    OpenXRControllerHapticSource,
)
from isaacteleop.retargeting_engine.tensor_types import ControllerHapticPulse


_PulseCall = Tuple[object, str, float, float, float]


class _RecordingControllerTracker:
    """Test double for ``ControllerTracker``.

    Implements just enough of the surface used by ``OpenXRControllerHapticSource``:
    ``apply_haptic_feedback`` records the call; ``fail_sides`` makes selected
    sides raise so we can exercise the once-per-side error gate.
    """

    def __init__(self, fail_sides: tuple[str, ...] = ()) -> None:
        self.calls: List[_PulseCall] = []
        self.fail_sides = set(fail_sides)

    def apply_haptic_feedback(self, session, side, amplitude, frequency_hz, duration_s):
        if side in self.fail_sides:
            raise RuntimeError(f"simulated tracker failure on {side}")
        self.calls.append((session, side, amplitude, frequency_hz, duration_s))


# ---------------------------------------------------------------------------
# OpenXRControllerHapticDevice
# ---------------------------------------------------------------------------


class TestOpenXRControllerHapticDevice:
    def test_accepted_type_is_controller_haptic_pulse(self) -> None:
        device = OpenXRControllerHapticDevice()
        assert device.accepted_type().name == ControllerHapticPulse().name

    def test_supports_reflects_sides_argument(self) -> None:
        device = OpenXRControllerHapticDevice(sides=("right",))
        assert not device.supports("left")
        assert device.supports("right")

    def test_apply_queues_per_side(self) -> None:
        device = OpenXRControllerHapticDevice()
        device.apply("left", np.array([0.4, 200.0, 0.05], dtype=np.float32))
        device.apply("right", np.array([0.7, 100.0, 0.10], dtype=np.float32))

        pending = device.drain_pending()
        assert set(pending.keys()) == {"left", "right"}
        # `apply()` round-trips through float32, so use approx on each scalar
        # rather than pytest.approx-in-dict (which compares element-wise via
        # __eq__ and does not see float32 rounding).
        l_amp, l_freq, l_dur = pending["left"]
        assert l_amp == pytest.approx(0.4)
        assert l_freq == pytest.approx(200.0)
        assert l_dur == pytest.approx(0.05)
        r_amp, r_freq, r_dur = pending["right"]
        assert r_amp == pytest.approx(0.7)
        assert r_freq == pytest.approx(100.0)
        assert r_dur == pytest.approx(0.10)

    def test_apply_coalesces_to_latest_per_side(self) -> None:
        """``xrApplyHapticFeedback`` already supersedes any in-flight pulse on
        the same action, so coalescing the queue to "latest wins" per side
        within one frame is correct, not lossy."""
        device = OpenXRControllerHapticDevice()
        device.apply("left", np.array([0.1, 0.0, 0.0], dtype=np.float32))
        device.apply("left", np.array([0.9, 0.0, 0.0], dtype=np.float32))

        pending = device.drain_pending()
        assert pending == {"left": (pytest.approx(0.9), 0.0, 0.0)}

    def test_drain_clears_queue(self) -> None:
        device = OpenXRControllerHapticDevice()
        device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))

        device.drain_pending()
        assert device.drain_pending() == {}

    def test_apply_rejects_wrong_shape(self) -> None:
        device = OpenXRControllerHapticDevice()
        with pytest.raises(ValueError, match="3-element"):
            device.apply("left", np.array([0.1, 0.2], dtype=np.float32))


# ---------------------------------------------------------------------------
# OpenXRControllerHapticSource
# ---------------------------------------------------------------------------


class TestOpenXRControllerHapticSource:
    def test_get_tracker_returns_constructor_handle(self) -> None:
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker()
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)
        assert source.get_tracker() is tracker

    def test_for_controllers_source_shares_tracker(self) -> None:
        """``for_controllers_source`` is the recommended path: it must hand
        out the *same* tracker instance the controllers source already owns,
        so ``DeviceIOSession`` deduplicates them by raw pointer."""
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker()

        class _DummyControllersSource:
            def __init__(self, t) -> None:
                self._t = t

            def get_tracker(self):
                return self._t

        controllers = _DummyControllersSource(tracker)
        source = OpenXRControllerHapticSource.for_controllers_source(
            "haptic_source", device, controllers
        )
        assert source.get_tracker() is tracker

    def test_poll_tracker_drains_and_forwards(self) -> None:
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker()
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)

        device.apply("left", np.array([0.3, 100.0, 0.05], dtype=np.float32))
        device.apply("right", np.array([0.7, 0.0, 0.0], dtype=np.float32))

        sentinel_session = object()
        result = source.poll_tracker(sentinel_session)

        assert result == {}, "no inputs declared, so an empty dict is correct"
        assert len(tracker.calls) == 2
        # Verify the session sentinel and field ordering reach the C++ binding
        # exactly as the tracker expects.
        sides = sorted(call[1] for call in tracker.calls)
        assert sides == ["left", "right"]
        for session, _side, amplitude, frequency_hz, duration_s in tracker.calls:
            assert session is sentinel_session
            assert isinstance(amplitude, float)
            assert isinstance(frequency_hz, float)
            assert isinstance(duration_s, float)

    def test_poll_tracker_leaves_queue_empty(self) -> None:
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker()
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)

        device.apply("left", np.array([0.3, 0.0, 0.0], dtype=np.float32))
        source.poll_tracker(object())
        assert device.drain_pending() == {}

    def test_poll_tracker_swallows_exceptions(self) -> None:
        """A failing tracker call must not propagate; haptic feedback is a
        nice-to-have and a hardware hiccup must not tear the session down."""
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker(fail_sides=("left",))
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)

        device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))
        device.apply("right", np.array([0.6, 0.0, 0.0], dtype=np.float32))

        # No exception should escape, even though "left" raises internally.
        source.poll_tracker(object())

        # The right side still gets through.
        assert [call[1] for call in tracker.calls] == ["right"]

    def test_poll_tracker_logs_failure_at_most_once_per_side(self, caplog) -> None:
        """Once-per-side log gate keeps a chronically failing side from
        flooding the log every frame."""
        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker(fail_sides=("left",))
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)

        for _ in range(3):
            device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))
            with caplog.at_level("WARNING"):
                source.poll_tracker(object())

        warnings = [
            r
            for r in caplog.records
            if "OpenXRControllerHapticSource" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            "expected a single once-per-side warning, "
            f"got {[r.getMessage() for r in warnings]}"
        )

    def test_compute_fn_sets_heartbeat(self) -> None:
        """The heartbeat output is only there so OutputCombiner discovers the
        source; ``poll_tracker`` does the real work, but ``_compute_fn`` must
        still produce a value or the graph errors out."""
        from isaacteleop.retargeting_engine.interface.base_retargeter import (
            _make_output_group,
        )

        device = OpenXRControllerHapticDevice()
        tracker = _RecordingControllerTracker()
        source = OpenXRControllerHapticSource("haptic_source", device, tracker)

        outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
        source.compute({}, outputs)
        assert outputs[OpenXRControllerHapticSource.HEARTBEAT][0] is True
