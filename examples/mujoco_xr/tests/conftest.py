# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Tests live in examples/mujoco_xr/tests/ but import the example's own package
# from examples/mujoco_xr/python/. Prepend that directory so
# `isaacteleop_examples.mujoco_xr` resolves against the in-tree source -- and,
# with it, the _mujoco_xr*.so that cpp/CMakeLists.txt builds in place beside
# __init__.py.
#
# STILL python/, not python/isaacteleop_examples/, even though the package moved
# a level deeper: `isaacteleop_examples` is a PEP 420 namespace, so what has to
# be on sys.path is the directory CONTAINING it. Pointing one level deeper would
# resolve a bare `mujoco_xr`, which is exactly the import that no longer exists.
# The namespace has no __init__.py by design, and adding one here to "make the
# import work" would break the installed wheel's ability to share the namespace.
#
# Same mechanism as examples/camera_viz/tests/conftest.py, two levels deeper
# because our package sits under python/<namespace>/ rather than beside the
# tests. Doing it here rather than in the ctest ENVIRONMENT is what keeps a bare
# `pytest` in this directory working too.
#
# isaacteleop is NOT resolved here: it comes from the PYTHONPATH entry the
# ctest registration sets (${CMAKE_BINARY_DIR}/python_package/<config>), or
# from the ambient environment when run by hand.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import pytest  # noqa: E402  (must follow the sys.path insert above)

# ---------------------------------------------------------------------------
# A SYNTHETIC ARM, and it is not a convenience -- it is the only way several
# Tier-0 behaviours get covered on an UNFETCHED checkout.
#
# The shipped robots come from MuJoCo Menagerie, which is fetched rather than
# vendored, so every test that loads one has to skip when it is absent. That
# would leave the ctrlrange/jnt_range intersection, the jaw polarity table and
# the gravity feed-forward guard covered only on a machine that had run the
# fetch script. This model is authored here, always available, and deliberately
# built to make each of those distinguishable:
#
#   j1  ctrlrange WIDER than jnt_range   -> the SO-101 wrist_roll case, the one
#                                           that parks a real servo at rated
#                                           torque against a live joint limit
#   j2  ctrlrange NARROWER than jnt_range
#   j3  no ctrlrange at all              -> unlimited side must contribute
#                                           mjMAXVAL, not 0
#   j4  no jnt_range at all
#   j5  the two ranges bitwise equal     -> the Panda case, where taking the
#                                           intersection is a structural
#                                           identity and therefore cannot fail
#
# Five joints, so it is rank-deficient for a 6-D task exactly like the SO-101 --
# which is also what makes it a legal ns_gain = 0 row.
_SYNTHETIC_ARM_XML = """
<mujoco model="synthetic arm">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.002"/>
  <worldbody>
    <body name="link1" pos="0 0 0">
      <joint name="j1" type="hinge" axis="0 0 1" range="-1.0 1.0"/>
      <geom type="box" size="0.05 0.01 0.01" pos="0.05 0 0" mass="0.1"/>
      <body name="link2" pos="0.1 0 0">
        <joint name="j2" type="hinge" axis="0 1 0" range="-2.0 2.0"/>
        <geom type="box" size="0.05 0.01 0.01" pos="0.05 0 0" mass="0.1"/>
        <body name="link3" pos="0.1 0 0">
          <joint name="j3" type="hinge" axis="0 1 0" range="-2.0 2.0"/>
          <geom type="box" size="0.05 0.01 0.01" pos="0.05 0 0" mass="0.1"/>
          <body name="link4" pos="0.1 0 0">
            <joint name="j4" type="hinge" axis="0 1 0" limited="false"/>
            <geom type="box" size="0.05 0.01 0.01" pos="0.05 0 0" mass="0.1"/>
            <body name="link5" pos="0.1 0 0">
              <joint name="j5" type="hinge" axis="1 0 0" range="-1.5 1.5"/>
              <geom type="box" size="0.05 0.01 0.01" pos="0.05 0 0" mass="0.1"/>
              <body name="tool" pos="0.1 0 0">
                <joint name="jaw" type="hinge" axis="0 1 0" range="-0.2 1.8"/>
                <geom type="box" size="0.01 0.01 0.01" mass="0.01"/>
              </body>
            </body>
          </body>
        </body>
      </body>
    </body>
  </worldbody>
  <actuator>
    <position name="a1" joint="j1" kp="50" ctrlrange="-1.5 1.5"/>
    <position name="a2" joint="j2" kp="50" ctrlrange="-0.5 0.5"/>
    <position name="a3" joint="j3" kp="50"/>
    <position name="a4" joint="j4" kp="50" ctrlrange="-3.0 3.0"/>
    <position name="a5" joint="j5" kp="50" ctrlrange="-1.5 1.5"/>
    <position name="ajaw" joint="jaw" kp="20" ctrlrange="-0.2 1.8"/>
  </actuator>
  <keyframe>
    <key name="home" qpos="0 0.3 -0.3 0.2 0 1.8" ctrl="0 0.3 -0.3 0.2 0 1.8"/>
  </keyframe>
</mujoco>
"""

# The intersection each joint above must produce. Written out rather than
# recomputed from the XML: a test that derives its expectation the same way the
# code does checks nothing.
SYNTHETIC_CTRL_BOUNDS = {
    "j1": (-1.0, 1.0),  # jnt_range wins on both sides
    "j2": (-0.5, 0.5),  # ctrlrange wins on both sides
    "j3": (-2.0, 2.0),  # no ctrlrange -> jnt_range alone
    "j4": (-3.0, 3.0),  # no jnt_range -> ctrlrange alone
    "j5": (-1.5, 1.5),  # equal
}


@pytest.fixture
def synthetic_arm_xml():
    return _SYNTHETIC_ARM_XML


@pytest.fixture
def synthetic_robot():
    """The ``robot_spec.Robot`` row describing the synthetic arm."""
    robot_spec = pytest.importorskip("isaacteleop_examples.mujoco_xr.robot_spec")
    return robot_spec.Robot(
        tcp_body="tool",
        joints=("j1", "j2", "j3", "j4", "j5"),
        gripper_act="ajaw",
        tcp_offset=(0.02, 0.0, 0.0),
        w_rot=1.0,
        dls_lambda=0.05,
        ns_gain=0.0,
        clutch_scale=1.0,
        gripper_closed=-0.2,
        gripper_open=1.8,
    )


@pytest.fixture
def synthetic_model(synthetic_arm_xml):
    mujoco = pytest.importorskip("mujoco")
    return mujoco.MjModel.from_xml_string(synthetic_arm_xml)


@pytest.fixture
def use_synthetic_table(monkeypatch, synthetic_robot):
    """Point ``robot_spec.ROBOTS`` at the synthetic row for one test.

    Patching the TABLE rather than adding a ``spec=`` argument to ``IkDls``:
    the production rule is that the robot is probed from the model and can never
    be asserted by a caller, and a test-only override parameter would put a hole
    in exactly that.
    """
    robot_spec = pytest.importorskip("isaacteleop_examples.mujoco_xr.robot_spec")
    monkeypatch.setattr(robot_spec, "ROBOTS", (synthetic_robot,))
    return synthetic_robot
