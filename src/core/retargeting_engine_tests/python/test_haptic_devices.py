# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ``isaacteleop.haptic_devices`` adapters.

``ControllerHapticDevice`` is the in-process device archetype and
``PushTensorHapticDevice`` (with the ``haptic_glove_device`` factory) is the
cross-process archetype. Both store per-endpoint values in ``apply()`` (called
inside the retargeting graph, no session in scope) and write them out in
``flush(session)`` (called by ``TeleopSession`` after the graph). We lock down:

* Store/emit semantics (latest-wins coalescing per endpoint, flush clears).
* Shape validation on ``apply()``.
* ``flush`` forwards each stored value to the device's tracker — the controller
  device calls the per-side ``apply_left_haptic_feedback`` /
  ``apply_right_haptic_feedback``; the push device encodes a ``HapticCommand``
  and ``push``-es it.
* ``flush`` swallows tracker exceptions and only logs once per endpoint.
* ``get_tracker`` / ``endpoints`` / ``accepted_type`` reflect construction.
"""

from typing import List, Tuple

import numpy as np
import pytest

from isaacteleop.haptic_devices.controller import ControllerHapticDevice
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulse,
    FingerPowerVector,
)


_PulseCall = Tuple[object, str, float, float, float]


class _RecordingControllerTracker:
    """Test double for ``ControllerTracker``.

    Implements just enough of the surface ``ControllerHapticDevice`` uses: the
    per-side ``apply_left_haptic_feedback`` / ``apply_right_haptic_feedback``
    record the call (tagged with the side); ``fail_endpoints`` makes selected
    sides raise so we can exercise the once-per-endpoint error gate.
    """

    def __init__(self, fail_endpoints: tuple[str, ...] = ()) -> None:
        self.calls: List[_PulseCall] = []
        self.fail_endpoints = set(fail_endpoints)

    def apply_left_haptic_feedback(self, session, amplitude, frequency_hz, duration_s):
        self._record("left", session, amplitude, frequency_hz, duration_s)

    def apply_right_haptic_feedback(self, session, amplitude, frequency_hz, duration_s):
        self._record("right", session, amplitude, frequency_hz, duration_s)

    def _record(self, side, session, amplitude, frequency_hz, duration_s):
        if side in self.fail_endpoints:
            raise RuntimeError(f"simulated tracker failure on {side}")
        self.calls.append((session, side, amplitude, frequency_hz, duration_s))


class TestControllerHapticDevice:
    def test_accepted_type_is_controller_haptic_pulse(self) -> None:
        device = ControllerHapticDevice(_RecordingControllerTracker())
        assert device.accepted_type().name == ControllerHapticPulse().name

    def test_endpoints_reflect_constructor(self) -> None:
        device = ControllerHapticDevice(
            _RecordingControllerTracker(), endpoints=("right",)
        )
        assert device.endpoints() == ("right",)

    def test_rejects_unsupported_endpoints(self) -> None:
        with pytest.raises(ValueError, match="only supports 'left'/'right'"):
            ControllerHapticDevice(
                _RecordingControllerTracker(), endpoints=("left", "device")
            )

    def test_get_tracker_returns_constructor_handle(self) -> None:
        tracker = _RecordingControllerTracker()
        device = ControllerHapticDevice(tracker)
        assert device.get_tracker() is tracker

    def test_apply_then_flush_forwards_per_endpoint(self) -> None:
        tracker = _RecordingControllerTracker()
        device = ControllerHapticDevice(tracker)

        device.apply("left", np.array([0.4, 200.0, 0.05], dtype=np.float32))
        device.apply("right", np.array([0.7, 100.0, 0.10], dtype=np.float32))

        sentinel_session = object()
        device.flush(sentinel_session)

        assert len(tracker.calls) == 2
        # Verify the session sentinel and field ordering reach the C++ binding
        # exactly as the tracker expects.
        endpoints = sorted(call[1] for call in tracker.calls)
        assert endpoints == ["left", "right"]
        for session, _endpoint, amplitude, frequency_hz, duration_s in tracker.calls:
            assert session is sentinel_session
            assert isinstance(amplitude, float)
            assert isinstance(frequency_hz, float)
            assert isinstance(duration_s, float)

    def test_apply_coalesces_to_latest_per_endpoint(self) -> None:
        """``xrApplyHapticFeedback`` already supersedes any in-flight pulse on
        the same action, so coalescing to "latest wins" per endpoint within one
        frame is correct, not lossy."""
        tracker = _RecordingControllerTracker()
        device = ControllerHapticDevice(tracker)

        device.apply("left", np.array([0.1, 0.0, 0.0], dtype=np.float32))
        device.apply("left", np.array([0.9, 0.0, 0.0], dtype=np.float32))
        device.flush(object())

        assert len(tracker.calls) == 1
        assert tracker.calls[0][1] == "left"
        assert tracker.calls[0][2] == pytest.approx(0.9)

    def test_flush_clears_pending(self) -> None:
        tracker = _RecordingControllerTracker()
        device = ControllerHapticDevice(tracker)

        device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))
        device.flush(object())
        device.flush(object())

        assert len(tracker.calls) == 1

    def test_apply_rejects_wrong_shape(self) -> None:
        device = ControllerHapticDevice(_RecordingControllerTracker())
        with pytest.raises(ValueError, match="3-element"):
            device.apply("left", np.array([0.1, 0.2], dtype=np.float32))

    def test_flush_swallows_exceptions(self) -> None:
        """A failing tracker call must not propagate; haptic feedback is a
        nice-to-have and a hardware hiccup must not tear the session down."""
        tracker = _RecordingControllerTracker(fail_endpoints=("left",))
        device = ControllerHapticDevice(tracker)

        device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))
        device.apply("right", np.array([0.6, 0.0, 0.0], dtype=np.float32))

        # No exception should escape, even though "left" raises internally.
        device.flush(object())

        # The right endpoint still gets through.
        assert [call[1] for call in tracker.calls] == ["right"]

    def test_flush_logs_failure_at_most_once_per_endpoint(self, caplog) -> None:
        """Once-per-endpoint log gate keeps a chronically failing endpoint from
        flooding the log every frame."""
        tracker = _RecordingControllerTracker(fail_endpoints=("left",))
        device = ControllerHapticDevice(tracker)

        for _ in range(3):
            device.apply("left", np.array([0.4, 0.0, 0.0], dtype=np.float32))
            with caplog.at_level("WARNING"):
                device.flush(object())

        warnings = [
            r for r in caplog.records if "ControllerHapticDevice" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            "expected a single once-per-endpoint warning, "
            f"got {[r.getMessage() for r in warnings]}"
        )


class _RecordingTensorPushTracker:
    """Test double for ``TensorPushTracker``.

    Records ``push(session, payload)`` calls; ``fail=True`` makes every push
    raise so we can exercise ``PushTensorHapticDevice``'s once-per-endpoint
    error gate. The endpoint is encoded inside ``payload`` (a HapticCommand
    FlatBuffer), so tests assert on the raw bytes.
    """

    def __init__(self, fail: bool = False) -> None:
        self.pushes: List[Tuple[object, bytes]] = []
        self._fail = fail

    def get_name(self) -> str:
        return "TensorPushTracker"

    def push(self, session, payload) -> None:
        if self._fail:
            raise RuntimeError("simulated push failure")
        self.pushes.append((session, bytes(payload)))


class TestPushTensorHapticDevice:
    """Cross-process device: ``apply`` stores, ``flush`` encodes one
    ``HapticCommand`` per endpoint and pushes it through a ``TensorPushTracker``.
    The real tracker is swapped for a recording double so ``flush`` can run
    without a live DeviceIO session."""

    def _device(self, **kwargs):
        from isaacteleop.haptic_devices.push_tensor import PushTensorHapticDevice

        return PushTensorHapticDevice("test_collection", FingerPowerVector(5), **kwargs)

    def test_accepted_type_reflects_constructor(self) -> None:
        device = self._device()
        assert device.accepted_type().name == FingerPowerVector(5).name

    def test_endpoints_reflect_constructor(self) -> None:
        device = self._device(endpoints=("device",))
        assert device.endpoints() == ("device",)

    def test_glove_factory_builds_finger_power_device(self) -> None:
        from isaacteleop.haptic_devices.glove import haptic_glove_device

        device = haptic_glove_device("manus_glove_haptic")
        assert device.accepted_type().name == FingerPowerVector(5).name
        assert device.endpoints() == ("left", "right")

    def test_apply_then_flush_pushes_encoded_command_per_endpoint(self) -> None:
        device = self._device()
        recorder = _RecordingTensorPushTracker()
        device._tracker = recorder  # swap in the double; flush() needs no session

        device.apply("left", np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32))
        device.apply("right", np.zeros(5, dtype=np.float32))

        sentinel_session = object()
        device.flush(sentinel_session)

        assert len(recorder.pushes) == 2
        for session, payload in recorder.pushes:
            assert session is sentinel_session
            assert isinstance(payload, bytes) and len(payload) > 0
        # The endpoint name travels inside the serialized HapticCommand.
        all_bytes = b"".join(payload for _s, payload in recorder.pushes)
        assert b"left" in all_bytes
        assert b"right" in all_bytes

    def test_apply_coalesces_to_latest_per_endpoint(self) -> None:
        device = self._device()
        recorder = _RecordingTensorPushTracker()
        device._tracker = recorder

        device.apply("left", np.full(5, 0.1, dtype=np.float32))
        device.apply("left", np.full(5, 0.9, dtype=np.float32))
        device.flush(object())

        assert len(recorder.pushes) == 1

    def test_flush_clears_pending(self) -> None:
        device = self._device()
        recorder = _RecordingTensorPushTracker()
        device._tracker = recorder

        device.apply("left", np.zeros(5, dtype=np.float32))
        device.flush(object())
        device.flush(object())

        assert len(recorder.pushes) == 1

    def test_flush_swallows_exceptions_and_logs_once_per_endpoint(self, caplog) -> None:
        device = self._device(endpoints=("left",))
        device._tracker = _RecordingTensorPushTracker(fail=True)

        for _ in range(3):
            device.apply("left", np.zeros(5, dtype=np.float32))
            with caplog.at_level("WARNING"):
                device.flush(object())  # must not raise

        warnings = [
            r for r in caplog.records if "PushTensorHapticDevice" in r.getMessage()
        ]
        assert len(warnings) == 1


class TestPackHapticCommand:
    def test_pack_returns_nonempty_bytes_with_endpoint(self) -> None:
        from isaacteleop.schema import pack_haptic_command

        payload = pack_haptic_command("left", [0.1, 0.2, 0.3, 0.4, 0.5])
        assert isinstance(payload, bytes) and len(payload) > 0
        # FlatBuffers stores the endpoint string inline.
        assert b"left" in payload
