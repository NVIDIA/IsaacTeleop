# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for SharpaHandRetargeter.

Resolves a stripped-down MJCF (no mesh references) from the
``robotic_grounding`` wheel via ``importlib.resources``. Requires
the ``grounding`` optional extra; tests skip cleanly otherwise.
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

_HAS_PINOCCHIO = True
try:
    from isaacteleop.retargeters import (
        SharpaHandRetargeter,
        SharpaHandRetargeterConfig,
    )
except ModuleNotFoundError:
    _HAS_PINOCCHIO = False

_requires_pinocchio = pytest.mark.skipif(
    not _HAS_PINOCCHIO,
    reason=(
        "requires robotic_grounding (pip install 'isaacteleop[grounding]' + "
        "scripts/setup_v2d_src.sh, see src/retargeters/README.md)"
    ),
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Sharpa MJCFs ship inside the robotic_grounding wheel as package_data.
# The _nomesh variant strips <mesh>/<asset> blocks so Pinocchio can load the
# model without the 24 MB of LFS-tracked STL meshes -- exactly what we need
# for hermetic unit tests.
if _HAS_PINOCCHIO:
    from importlib.resources import files as _files

    SHARPA_MJCF = str(
        _files("robotic_grounding")
        / "assets"
        / "xmls"
        / "sharpawave"
        / "right_sharpawave_nomesh.xml"
    )
else:
    SHARPA_MJCF = ""  # tests are skipped via _HAS_PINOCCHIO anyway

# ---------------------------------------------------------------------------
# Helpers (mirror test_dual_input_retargeters.py patterns)
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


def _make_hand_input_open() -> TensorGroup:
    """Build a straight / open hand pose at the origin."""
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    orientations = np.tile(ID_QUAT, (NUM_HAND_JOINTS, 1))
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    # Wrist at origin
    positions[HandJointIndex.WRIST] = [0, 0, 0]

    # Thumb: straight along +X +Y
    positions[HandJointIndex.THUMB_METACARPAL] = [0.02, 0.02, 0]
    positions[HandJointIndex.THUMB_PROXIMAL] = [0.04, 0.04, 0]
    positions[HandJointIndex.THUMB_DISTAL] = [0.06, 0.06, 0]
    positions[HandJointIndex.THUMB_TIP] = [0.08, 0.08, 0]

    # Index: straight along +Z
    positions[HandJointIndex.INDEX_PROXIMAL] = [0, 0.03, 0.04]
    positions[HandJointIndex.INDEX_INTERMEDIATE] = [0, 0.03, 0.07]
    positions[HandJointIndex.INDEX_DISTAL] = [0, 0.03, 0.10]
    positions[HandJointIndex.INDEX_TIP] = [0, 0.03, 0.13]

    # Middle
    positions[HandJointIndex.MIDDLE_PROXIMAL] = [0, 0.01, 0.04]
    positions[HandJointIndex.MIDDLE_INTERMEDIATE] = [0, 0.01, 0.07]
    positions[HandJointIndex.MIDDLE_DISTAL] = [0, 0.01, 0.10]
    positions[HandJointIndex.MIDDLE_TIP] = [0, 0.01, 0.13]

    # Ring
    positions[HandJointIndex.RING_PROXIMAL] = [0, -0.01, 0.04]
    positions[HandJointIndex.RING_INTERMEDIATE] = [0, -0.01, 0.07]
    positions[HandJointIndex.RING_DISTAL] = [0, -0.01, 0.10]
    positions[HandJointIndex.RING_TIP] = [0, -0.01, 0.13]

    # Pinky
    positions[HandJointIndex.LITTLE_PROXIMAL] = [0, -0.03, 0.04]
    positions[HandJointIndex.LITTLE_INTERMEDIATE] = [0, -0.03, 0.07]
    positions[HandJointIndex.LITTLE_DISTAL] = [0, -0.03, 0.10]
    positions[HandJointIndex.LITTLE_TIP] = [0, -0.03, 0.13]

    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


def _make_hand_input_curled() -> TensorGroup:
    """Build a hand pose with curled fingers."""
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    orientations = np.tile(ID_QUAT, (NUM_HAND_JOINTS, 1))
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    positions[HandJointIndex.WRIST] = [0, 0, 0]

    # Thumb (slightly curved)
    positions[HandJointIndex.THUMB_METACARPAL] = [0.02, 0.02, 0]
    positions[HandJointIndex.THUMB_PROXIMAL] = [0.04, 0.04, 0]
    positions[HandJointIndex.THUMB_DISTAL] = [0.05, 0.05, -0.01]
    positions[HandJointIndex.THUMB_TIP] = [0.055, 0.055, -0.025]

    # Index (curled)
    positions[HandJointIndex.INDEX_PROXIMAL] = [0, 0.03, 0.04]
    positions[HandJointIndex.INDEX_INTERMEDIATE] = [0, 0.03, 0.07]
    positions[HandJointIndex.INDEX_DISTAL] = [-0.02, 0.03, 0.08]
    positions[HandJointIndex.INDEX_TIP] = [-0.04, 0.03, 0.07]

    # Middle (curled)
    positions[HandJointIndex.MIDDLE_PROXIMAL] = [0, 0.01, 0.04]
    positions[HandJointIndex.MIDDLE_INTERMEDIATE] = [0, 0.01, 0.07]
    positions[HandJointIndex.MIDDLE_DISTAL] = [-0.02, 0.01, 0.08]
    positions[HandJointIndex.MIDDLE_TIP] = [-0.04, 0.01, 0.07]

    # Ring (curled)
    positions[HandJointIndex.RING_PROXIMAL] = [0, -0.01, 0.04]
    positions[HandJointIndex.RING_INTERMEDIATE] = [0, -0.01, 0.07]
    positions[HandJointIndex.RING_DISTAL] = [-0.02, -0.01, 0.08]
    positions[HandJointIndex.RING_TIP] = [-0.04, -0.01, 0.07]

    # Pinky (curled)
    positions[HandJointIndex.LITTLE_PROXIMAL] = [0, -0.03, 0.04]
    positions[HandJointIndex.LITTLE_INTERMEDIATE] = [0, -0.03, 0.07]
    positions[HandJointIndex.LITTLE_DISTAL] = [-0.02, -0.03, 0.08]
    positions[HandJointIndex.LITTLE_TIP] = [-0.04, -0.03, 0.07]

    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


# ---------------------------------------------------------------------------
# Expected joint names from the MJCF (22 finger DOFs)
# ---------------------------------------------------------------------------

EXPECTED_FINGER_JOINTS = [
    "right_thumb_CMC_FE",
    "right_thumb_CMC_AA",
    "right_thumb_MCP_FE",
    "right_thumb_MCP_AA",
    "right_thumb_IP",
    "right_index_MCP_FE",
    "right_index_MCP_AA",
    "right_index_PIP",
    "right_index_DIP",
    "right_middle_MCP_FE",
    "right_middle_MCP_AA",
    "right_middle_PIP",
    "right_middle_DIP",
    "right_ring_MCP_FE",
    "right_ring_MCP_AA",
    "right_ring_PIP",
    "right_ring_DIP",
    "right_pinky_CMC",
    "right_pinky_MCP_FE",
    "right_pinky_MCP_AA",
    "right_pinky_PIP",
    "right_pinky_DIP",
]


# ===========================================================================
# Tests
# ===========================================================================


@_requires_pinocchio
class TestSharpaHandRetargeter:
    @pytest.fixture()
    def retargeter(self):
        cfg = SharpaHandRetargeterConfig(
            robot_asset_path=SHARPA_MJCF,
            hand_side="right",
            max_iter=50,
            frequency=200.0,
        )
        return SharpaHandRetargeter(cfg, name="sharpa_test")

    def test_init_loads_model(self, retargeter):
        """Verify model loading discovers the expected finger joints."""
        spec = retargeter.output_spec()
        joint_names = [t.name for t in spec["hand_joints"].types]
        assert joint_names == EXPECTED_FINGER_JOINTS

    def test_input_spec_has_hand_key(self, retargeter):
        spec = retargeter.input_spec()
        assert "hand_right" in spec

    def test_absent_hand_outputs_zeros(self, retargeter):
        """Absent (optional) hand input should produce all-zero output."""
        inputs, outputs = _build_io(retargeter)
        retargeter.compute(inputs, outputs, _make_context())

        for i in range(len(EXPECTED_FINGER_JOINTS)):
            assert outputs["hand_joints"][i] == pytest.approx(0.0)

    def test_open_hand_produces_output(self, retargeter):
        """An open hand pose should produce finite joint angles."""
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_open()

        retargeter.compute(inputs, outputs, _make_context())

        values = [
            float(outputs["hand_joints"][i]) for i in range(len(EXPECTED_FINGER_JOINTS))
        ]
        assert all(np.isfinite(values)), f"Non-finite values: {values}"

    def test_curled_hand_produces_nonzero_joints(self, retargeter):
        """A curled hand should produce noticeably non-zero joint angles."""
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()

        retargeter.compute(inputs, outputs, _make_context())

        values = [
            float(outputs["hand_joints"][i]) for i in range(len(EXPECTED_FINGER_JOINTS))
        ]
        assert any(abs(v) > 0.01 for v in values), (
            f"Expected at least some non-zero joints for curled hand, got: {values}"
        )

    def test_warm_starting_persistence(self, retargeter):
        """Second frame should reuse warm-start from the first frame."""
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()

        retargeter.compute(inputs, outputs, _make_context())
        assert retargeter._qpos_prev is not None, (
            "qpos_prev should be set after first frame"
        )

        qpos_after_first = retargeter._qpos_prev.copy()

        # Slightly perturbed pose for second frame
        inputs2, outputs2 = _build_io(retargeter)
        hand2 = _make_hand_input_curled()
        positions = np.from_dlpack(hand2[HandInputIndex.JOINT_POSITIONS]).copy()
        positions += 0.001  # small perturbation
        hand2[HandInputIndex.JOINT_POSITIONS] = positions
        inputs2["hand_right"] = hand2

        retargeter.compute(inputs2, outputs2, _make_context())

        qpos_after_second = retargeter._qpos_prev.copy()

        # The second qpos should be close to the first (warm-started)
        # but not identical (different input). Skip the 7-DOF FreeFlyer
        # prefix (3 translation + 4 quat) that the wrist pose is anchored to.
        FREEFLYER_NQ = 7
        diff = np.linalg.norm(
            qpos_after_second[FREEFLYER_NQ:] - qpos_after_first[FREEFLYER_NQ:]
        )
        assert diff < 1.0, (
            f"Warm-started second frame should be close to first, diff={diff}"
        )

    def test_absent_then_valid_resets_warm_start(self, retargeter):
        """Feeding absent input should reset warm-start state."""
        inputs, outputs = _build_io(retargeter)
        inputs["hand_right"] = _make_hand_input_curled()
        retargeter.compute(inputs, outputs, _make_context())
        assert retargeter._qpos_prev is not None

        # Feed absent input
        inputs_absent, outputs_absent = _build_io(retargeter)
        retargeter.compute(inputs_absent, outputs_absent, _make_context())
        assert retargeter._qpos_prev is None, (
            "qpos_prev should be reset after absent input"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
