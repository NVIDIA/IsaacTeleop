# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for WujiHandRetargeter.

Requires the ``wuji`` optional extra (``pip install 'isaacteleop[wuji]'``,
which brings in ``wuji-sdk[retarget]``); tests skip cleanly otherwise.

The C++/Python joint-mapping cross-check lives in
test_wuji_mapping_tables.py, which has no SDK dependency and therefore runs
in the plain dev environment.
"""

import numpy as np
import pytest

from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    ExecutionEvents,
    ExecutionState,
    OptionalTensorGroup,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalTensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    HandInput,
    HandInputIndex,
    HandJointIndex,
    NUM_HAND_JOINTS,
)

# Gate on the wuji extra with collected-then-skipped semantics rather than a
# module-level importorskip: skipping at collection leaves pytest with zero
# collected tests and exit code 5, which CTest treats as a failure.
_HAS_WUJI_SDK = True
try:
    from isaacteleop.retargeters import (
        WujiHandRetargeter,
        WujiHandRetargeterConfig,
    )
except ModuleNotFoundError:
    _HAS_WUJI_SDK = False

_requires_wuji_sdk = pytest.mark.skipif(
    not _HAS_WUJI_SDK,
    reason="requires wuji_sdk (pip install 'isaacteleop[wuji]')",
)

NUM_WUJI_JOINTS = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _make_context(*, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _build_io(retargeter):
    inputs = {}
    for k, v in retargeter.input_spec().items():
        if isinstance(v, OptionalTensorGroupType):
            inputs[k] = OptionalTensorGroup(v)
        else:
            inputs[k] = TensorGroup(v)
    outputs = {}
    for k, v in retargeter.output_spec().items():
        if isinstance(v, OptionalTensorGroupType):
            outputs[k] = OptionalTensorGroup(v)
        else:
            outputs[k] = TensorGroup(v)
    return inputs, outputs


def _make_hand_input_curled() -> TensorGroup:
    """A right hand with curled fingers, wrist-relative, MediaPipe-compatible."""
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    orientations = np.tile(ID_QUAT, (NUM_HAND_JOINTS, 1))
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    positions[HandJointIndex.WRIST] = [0, 0, 0]

    positions[HandJointIndex.THUMB_METACARPAL] = [0.02, 0.02, 0]
    positions[HandJointIndex.THUMB_PROXIMAL] = [0.04, 0.04, 0]
    positions[HandJointIndex.THUMB_DISTAL] = [0.05, 0.05, -0.01]
    positions[HandJointIndex.THUMB_TIP] = [0.055, 0.055, -0.025]

    positions[HandJointIndex.INDEX_PROXIMAL] = [0, 0.03, 0.04]
    positions[HandJointIndex.INDEX_INTERMEDIATE] = [0, 0.03, 0.07]
    positions[HandJointIndex.INDEX_DISTAL] = [-0.02, 0.03, 0.08]
    positions[HandJointIndex.INDEX_TIP] = [-0.04, 0.03, 0.07]

    positions[HandJointIndex.MIDDLE_PROXIMAL] = [0, 0.01, 0.04]
    positions[HandJointIndex.MIDDLE_INTERMEDIATE] = [0, 0.01, 0.07]
    positions[HandJointIndex.MIDDLE_DISTAL] = [-0.02, 0.01, 0.08]
    positions[HandJointIndex.MIDDLE_TIP] = [-0.04, 0.01, 0.07]

    positions[HandJointIndex.RING_PROXIMAL] = [0, -0.01, 0.04]
    positions[HandJointIndex.RING_INTERMEDIATE] = [0, -0.01, 0.07]
    positions[HandJointIndex.RING_DISTAL] = [-0.02, -0.01, 0.08]
    positions[HandJointIndex.RING_TIP] = [-0.04, -0.01, 0.07]

    positions[HandJointIndex.LITTLE_PROXIMAL] = [0, -0.03, 0.04]
    positions[HandJointIndex.LITTLE_INTERMEDIATE] = [0, -0.03, 0.07]
    positions[HandJointIndex.LITTLE_DISTAL] = [-0.02, -0.03, 0.08]
    positions[HandJointIndex.LITTLE_TIP] = [-0.04, -0.03, 0.07]

    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


def _output_values(outputs) -> list:
    return [float(outputs["hand_joints"][i]) for i in range(NUM_WUJI_JOINTS)]


# ===========================================================================
# Tests
# ===========================================================================


@_requires_wuji_sdk
class TestWujiHandRetargeter:
    @pytest.fixture()
    def retargeter(self):
        cfg = WujiHandRetargeterConfig(model="wuji_hand_2", hand_side="right")
        return WujiHandRetargeter(cfg, name="wuji_test")

    def test_output_spec_is_20_dofs_finger_major(self, retargeter):
        spec = retargeter.output_spec()
        joint_names = [t.name for t in spec["hand_joints"].types]
        expected = [
            f"{finger}_j{k}"
            for finger in ("thumb", "index", "middle", "ring", "pinky")
            for k in range(4)
        ]
        assert joint_names == expected
        assert [t.name for t in spec["hand_valid"].types] == ["valid"]

    def test_input_spec_has_hand_key(self, retargeter):
        spec = retargeter.input_spec()
        assert "hand_right" in spec

    def test_absent_hand_outputs_zeros_and_invalid(self, retargeter):
        """Absent (optional) hand input emits zeros and hand_valid=0.

        The drive demo relies on hand_valid to detect dropouts and hold the
        last valid command instead of forwarding zeros to hardware.
        """
        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context())
        assert _output_values(outputs) == pytest.approx([0.0] * NUM_WUJI_JOINTS)
        assert float(outputs["hand_valid"][0]) == 0.0

    def test_single_invalid_joint_outputs_zeros(self, retargeter):
        """The validity gate is all-or-nothing over the 21 mapped joints."""
        inputs, outputs = _build_io(retargeter)
        hand = _make_hand_input_curled()
        valid = np.from_dlpack(hand[HandInputIndex.JOINT_VALID]).copy()
        valid[HandJointIndex.INDEX_TIP] = 0
        hand[HandInputIndex.JOINT_VALID] = valid
        inputs["hand_right"] = hand

        retargeter.compute(inputs, outputs, _make_context())
        assert _output_values(outputs) == pytest.approx([0.0] * NUM_WUJI_JOINTS)
        assert float(outputs["hand_valid"][0]) == 0.0

    def test_curled_hand_produces_finite_nonzero_output(self, retargeter):
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()

        retargeter.compute(inputs, outputs, _make_context())

        values = _output_values(outputs)
        assert all(np.isfinite(values)), f"Non-finite values: {values}"
        assert any(abs(v) > 0.01 for v in values), (
            f"Expected some non-zero joints for a curled hand, got: {values}"
        )
        assert float(outputs["hand_valid"][0]) == 1.0

    def test_gap_resets_session_state(self, retargeter):
        """A tracking gap must drop warm-start/smoothing state.

        The first frame after a gap should match the very first frame this
        retargeter ever produced for the same input — if the gap did not
        reset the session, smoothing toward the pre-gap pose would drag the
        output away from the cold-start result.
        """
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()
        retargeter.compute(inputs, outputs, _make_context())
        first = _output_values(outputs)

        # Tracking gap: absent input emits zeros and resets the session.
        inputs_absent, outputs_absent = _build_io(retargeter)
        retargeter.compute(inputs_absent, outputs_absent, _make_context())

        inputs2, outputs2 = _build_io(retargeter)
        inputs2["hand_right"] = _make_hand_input_curled()
        retargeter.compute(inputs2, outputs2, _make_context())
        after_gap = _output_values(outputs2)

        assert after_gap == pytest.approx(first, abs=1e-4)

    def test_reset_event_resets_session_state(self, retargeter):
        """An explicit execution reset behaves like a tracking gap."""
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()
        retargeter.compute(inputs, outputs, _make_context())
        first = _output_values(outputs)

        # Warm the session with a second frame, then reset explicitly.
        retargeter.compute(inputs, outputs, _make_context())

        inputs2, outputs2 = _build_io(retargeter)
        inputs2["hand_right"] = _make_hand_input_curled()
        retargeter.compute(inputs2, outputs2, _make_context(reset=True))
        after_reset = _output_values(outputs2)

        assert after_reset == pytest.approx(first, abs=1e-4)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
