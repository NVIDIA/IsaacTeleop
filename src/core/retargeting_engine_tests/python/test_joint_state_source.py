# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the JointStateSource DeviceIO converter.

Exercises the stateless converter from a raw ``JointStateOutput`` FlatBuffer (constructed via the
real schema Python bindings) into the name-keyed joint-position tensor group consumed downstream,
with no OpenXR device involved.
"""

import pytest

from isaacteleop.retargeting_engine.deviceio_source_nodes import JointStateSource
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup
from isaacteleop.schema import JointState, JointStateOutput, JointStateOutputTrackedT

SO101_JOINTS = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


def _make_inputs(source, raw: dict) -> dict:
    spec = source.input_spec()
    result = {}
    for name, objects in raw.items():
        tg = TensorGroup(spec[name])
        for i, obj in enumerate(objects):
            tg[i] = obj
        result[name] = tg
    return result


def _outputs(source):
    return {name: _make_output_group(gt) for name, gt in source.output_spec().items()}


def _make_output(joint_values: dict) -> JointStateOutput:
    out = JointStateOutput()
    out.device_id = "so101_leader"
    out.joints = [JointState(name, pos) for name, pos in joint_values.items()]
    return out


class TestJointStateSource:
    def test_creation_and_tracker(self):
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=SO101_JOINTS
        )
        assert src.name == "leader"
        tracker = src.get_tracker()
        assert tracker is not None
        assert tracker.get_name() == "JointStateTracker"

    def test_input_output_spec(self):
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=SO101_JOINTS
        )
        assert list(src.input_spec()) == ["deviceio_joint_state"]
        out_spec = src.output_spec()
        assert list(out_spec) == [JointStateSource.JOINTS]
        assert out_spec[JointStateSource.JOINTS].is_optional
        names = [t.name for t in out_spec[JointStateSource.JOINTS].inner_type.types]
        assert names == SO101_JOINTS

    def test_active_conversion(self):
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=SO101_JOINTS
        )
        values = {n: round(0.1 * (i + 1), 3) for i, n in enumerate(SO101_JOINTS)}
        inputs = _make_inputs(
            src,
            {"deviceio_joint_state": [JointStateOutputTrackedT(_make_output(values))]},
        )
        outputs = _outputs(src)
        src.compute(inputs, outputs)

        group = outputs[JointStateSource.JOINTS]
        assert not group.is_none
        for i, n in enumerate(SO101_JOINTS):
            assert float(group[i]) == pytest.approx(values[n])

    def test_name_order_independent(self):
        """Joints arriving in a different order than joint_names are mapped by name."""
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=["a", "b", "c"]
        )
        # Schema joints intentionally in reverse order.
        out = _make_output({"c": 3.0, "a": 1.0, "b": 2.0})
        inputs = _make_inputs(
            src, {"deviceio_joint_state": [JointStateOutputTrackedT(out)]}
        )
        outputs = _outputs(src)
        src.compute(inputs, outputs)
        group = outputs[JointStateSource.JOINTS]
        assert float(group[0]) == pytest.approx(1.0)  # a
        assert float(group[1]) == pytest.approx(2.0)  # b
        assert float(group[2]) == pytest.approx(3.0)  # c

    def test_missing_joint_defaults_zero(self):
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=["a", "missing"]
        )
        out = _make_output({"a": 1.5})
        inputs = _make_inputs(
            src, {"deviceio_joint_state": [JointStateOutputTrackedT(out)]}
        )
        outputs = _outputs(src)
        src.compute(inputs, outputs)
        group = outputs[JointStateSource.JOINTS]
        assert float(group[0]) == pytest.approx(1.5)
        assert float(group[1]) == pytest.approx(0.0)

    def test_inactive_sets_none(self):
        src = JointStateSource(
            name="leader", collection_id="so101_leader", joint_names=SO101_JOINTS
        )
        # TrackedT with no data -> device inactive.
        inputs = _make_inputs(
            src, {"deviceio_joint_state": [JointStateOutputTrackedT()]}
        )
        outputs = _outputs(src)
        src.compute(inputs, outputs)
        assert outputs[JointStateSource.JOINTS].is_none
