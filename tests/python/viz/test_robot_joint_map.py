# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``isaacteleop.viz.robot.JointMap`` -- name to address, and the layout assert."""

import numpy as np
import pytest

from isaacteleop.viz.robot.joint_map import JointMap

_NAMES = ("shoulder", "elbow", "gripper")


def _map(names=_NAMES, addresses=(0, 1, 2), width=3):
    return JointMap(names, addresses, width=width)


def test_scatter_writes_each_name_to_its_own_address():
    """Addresses need not be contiguous, and the gaps must be left alone."""
    positions = np.full(6, -1.0)
    _map(addresses=(5, 0, 3), width=6).scatter([0.1, 0.2, 0.3], positions)
    np.testing.assert_allclose(positions, [0.2, -1.0, -1.0, 0.3, -1.0, 0.1])


@pytest.mark.parametrize(
    ("names", "addresses", "width"),
    [
        (_NAMES, (0, 1), 3),  # one address short
        (("a", "a"), (0, 1), 3),  # duplicate name
        (("a", "b"), (1, 1), 3),  # aliased address: the second would win
        (("a", "b"), (0, 3), 3),  # past the end
        (("a", "b"), (0, -1), 3),  # negative would index from the end
    ],
)
def test_rejects_a_mapping_nothing_could_scatter_through(names, addresses, width):
    with pytest.raises(ValueError):
        JointMap(names, addresses, width=width)


def test_require_accepts_the_authored_order():
    _map().require(_NAMES)


@pytest.mark.parametrize(
    "expected",
    [
        ("shoulder", "gripper", "elbow"),  # reordered: same joints, wrong angles
        ("shoulder", "elbow"),  # a joint the caller does not know about
        ("shoulder", "elbow", "wrist"),  # renamed upstream
    ],
)
def test_require_rejects_anything_else(expected):
    with pytest.raises(RuntimeError, match="pose the wrong joints"):
        _map().require(expected)


def test_require_names_what_differs():
    """The message has to be actionable: an operator sees it and nothing else."""
    with pytest.raises(RuntimeError) as excinfo:
        _map().require(("shoulder", "elbow", "wrist"))
    assert "wrist" in str(excinfo.value) and "gripper" in str(excinfo.value)


@pytest.mark.parametrize("joints", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], []])
def test_scatter_rejects_a_snapshot_of_the_wrong_width(joints):
    with pytest.raises(ValueError):
        _map().scatter(joints, np.zeros(3))


def test_scatter_rejects_a_state_vector_of_the_wrong_width():
    """Numpy would happily index a longer one, silently posing a different scene."""
    with pytest.raises(ValueError):
        _map().scatter([0.0, 0.0, 0.0], np.zeros(9))


def test_a_rigid_scene_maps_no_joints_at_all():
    """Legal, and what a prop moved only by its base pose has."""
    joints = JointMap((), (), width=0)
    assert len(joints) == 0
    joints.require(())
    joints.scatter([], np.zeros(0))
