# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
End-to-end tests for the spacemouse device: raw translation/rotation/button state
(constructed via the real schema Python bindings, no live device/plugin/OpenXR session
involved) flowing through SpaceMouseSource into SpaceMouseToSe3RelRetargeter,
SpaceMouseGripperRetargeter, and SpaceMouseToSe2Retargeter.

These exercise the full feature as a whole -- schema -> source -> retargeters -- so a
regression anywhere in that chain (a field rename, an index drift, a sign flip) fails
here, rather than testing each stage's internals in isolation.
"""

import numpy as np
import pytest
from isaacteleop.retargeters import (
    SpaceMouseGripperRetargeter,
    SpaceMouseToSe2Retargeter,
    SpaceMouseToSe2RetargeterConfig,
    SpaceMouseToSe3RelRetargeter,
    SpaceMouseToSe3RelRetargeterConfig,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import SpaceMouseSource
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup
from isaacteleop.schema import SpaceMouseOutput, SpaceMouseOutputTrackedT

BUTTON_LEFT = 0


def _spacemouse_source():
    return SpaceMouseSource(name="spacemouse")


def _run_source(
    src,
    translation: list[float] | None,
    rotation: list[float] | None = None,
    pressed_buttons: list[int] | None = None,
):
    """Feed raw translation/rotation/button state (None translation = inactive device) through SpaceMouseSource.compute()."""
    if translation is None:
        tracked = SpaceMouseOutputTrackedT()  # data is None -> inactive
    else:
        tracked = SpaceMouseOutputTrackedT(
            SpaceMouseOutput(
                translation, rotation or [0.0, 0.0, 0.0], pressed_buttons or [], True
            )
        )

    input_spec = src.input_spec()
    tg = TensorGroup(input_spec["deviceio_spacemouse"])
    tg[0] = tracked

    outputs = {name: _make_output_group(gt) for name, gt in src.output_spec().items()}
    src.compute({"deviceio_spacemouse": tg}, outputs)
    return outputs


class TestSpaceMouseEndToEnd:
    def test_source_creates_real_tracker(self):
        src = _spacemouse_source()
        tracker = src.get_tracker()
        assert tracker is not None
        assert tracker.get_name() == "SpaceMouseTracker"

    def test_translation_produces_position_delta(self):
        """translation[0] -> +Y, translation[1] -> +X, translation[2] -> -Z (inverted)."""
        src = _spacemouse_source()
        src_outputs = _run_source(src, translation=[1.0, 1.0, 1.0])

        retargeter = SpaceMouseToSe3RelRetargeter(
            SpaceMouseToSe3RelRetargeterConfig(), name="se3"
        )
        out = {"ee_delta": _make_output_group(retargeter.output_spec()["ee_delta"])}
        retargeter.compute(
            {
                "spacemouse_translation": src_outputs["spacemouse_translation"],
                "spacemouse_rotation": src_outputs["spacemouse_rotation"],
            },
            out,
        )

        delta = np.asarray(out["ee_delta"][0])
        assert delta[0] == pytest.approx(0.4)  # +X from translation[1]
        assert delta[1] == pytest.approx(0.4)  # +Y from translation[0]
        assert delta[2] == pytest.approx(-0.4)  # -Z from translation[2] (inverted)

    def test_se3_inactive_device_yields_zero_delta(self):
        src = _spacemouse_source()
        src_outputs = _run_source(src, translation=None)
        assert src_outputs["spacemouse_translation"].is_none
        assert src_outputs["spacemouse_rotation"].is_none

        se3 = SpaceMouseToSe3RelRetargeter(
            SpaceMouseToSe3RelRetargeterConfig(), name="se3"
        )
        se3_out = {"ee_delta": _make_output_group(se3.output_spec()["ee_delta"])}
        se3.compute(
            {
                "spacemouse_translation": src_outputs["spacemouse_translation"],
                "spacemouse_rotation": src_outputs["spacemouse_rotation"],
            },
            se3_out,
        )
        assert np.allclose(np.asarray(se3_out["ee_delta"][0]), 0.0)

    def test_gripper_toggles_on_button_rising_edge_only(self):
        """Left-button press/release/press across three frames toggles on each rising edge."""
        src = _spacemouse_source()
        retargeter = SpaceMouseGripperRetargeter(name="gripper")

        def step(pressed_buttons):
            src_outputs = _run_source(
                src, translation=[0.0, 0.0, 0.0], pressed_buttons=pressed_buttons
            )
            out = {
                "gripper_command": _make_output_group(
                    retargeter.output_spec()["gripper_command"]
                )
            }
            retargeter.compute(
                {"spacemouse_buttons": src_outputs["spacemouse_buttons"]}, out
            )
            return float(out["gripper_command"][0])

        assert step([]) == pytest.approx(1.0)  # open (default)
        assert step([BUTTON_LEFT]) == pytest.approx(-1.0)  # rising edge -> close
        assert step([BUTTON_LEFT]) == pytest.approx(
            -1.0
        )  # held -> stays closed, no re-toggle
        assert step([]) == pytest.approx(-1.0)  # release -> stays closed
        assert step([BUTTON_LEFT]) == pytest.approx(1.0)  # rising edge again -> open

    def test_gripper_inactive_device_yields_default_open(self):
        src = _spacemouse_source()
        src_outputs = _run_source(src, translation=None)

        gripper = SpaceMouseGripperRetargeter(name="gripper")
        gripper_out = {
            "gripper_command": _make_output_group(
                gripper.output_spec()["gripper_command"]
            )
        }
        gripper.compute(
            {"spacemouse_buttons": src_outputs["spacemouse_buttons"]}, gripper_out
        )
        assert float(gripper_out["gripper_command"][0]) == pytest.approx(
            1.0
        )  # default open

    def test_buttons_bitmap_covers_indices_outside_gripper_button(self):
        """A button other than the left one shows up in spacemouse_buttons but does not affect the gripper."""
        src = _spacemouse_source()
        src_outputs = _run_source(
            src, translation=[0.0, 0.0, 0.0], pressed_buttons=[1]
        )  # right button

        bitmap = np.asarray(src_outputs["spacemouse_buttons"][0])
        assert bitmap[1] == 1
        assert bitmap.sum() == 1

        gripper = SpaceMouseGripperRetargeter(name="gripper")
        gripper_out = {
            "gripper_command": _make_output_group(
                gripper.output_spec()["gripper_command"]
            )
        }
        gripper.compute(
            {"spacemouse_buttons": src_outputs["spacemouse_buttons"]}, gripper_out
        )
        assert float(gripper_out["gripper_command"][0]) == pytest.approx(
            1.0
        )  # unaffected

    def test_multiple_buttons_mark_bitmap(self):
        """Simultaneously-held buttons each show up in spacemouse_buttons."""
        src = _spacemouse_source()
        src_outputs = _run_source(
            src, translation=[0.0, 0.0, 0.0], pressed_buttons=[BUTTON_LEFT, 1]
        )

        bitmap = np.asarray(src_outputs["spacemouse_buttons"][0])
        assert bitmap[BUTTON_LEFT] == 1
        assert bitmap[1] == 1
        assert bitmap.sum() == 2

    def test_se2_translation_and_rotation_combine(self):
        """translation -> v_x/v_y, rotation[1] -> omega_z."""
        src = _spacemouse_source()
        src_outputs = _run_source(
            src, translation=[1.0, 1.0, 0.0], rotation=[0.0, 1.0, 0.0]
        )

        retargeter = SpaceMouseToSe2Retargeter(
            SpaceMouseToSe2RetargeterConfig(), name="se2"
        )
        out = {
            "base_command": _make_output_group(retargeter.output_spec()["base_command"])
        }
        retargeter.compute(
            {
                "spacemouse_translation": src_outputs["spacemouse_translation"],
                "spacemouse_rotation": src_outputs["spacemouse_rotation"],
            },
            out,
        )

        velocity = np.asarray(out["base_command"][0])
        assert velocity[0] == pytest.approx(1.0)  # v_x from translation[1]
        assert velocity[1] == pytest.approx(1.0)  # v_y from translation[0]
        assert velocity[2] == pytest.approx(1.0)  # omega_z from rotation[1]

    def test_se2_inactive_device_yields_zero_velocity(self):
        src = _spacemouse_source()
        src_outputs = _run_source(src, translation=None)

        retargeter = SpaceMouseToSe2Retargeter(
            SpaceMouseToSe2RetargeterConfig(), name="se2"
        )
        out = {
            "base_command": _make_output_group(retargeter.output_spec()["base_command"])
        }
        retargeter.compute(
            {
                "spacemouse_translation": src_outputs["spacemouse_translation"],
                "spacemouse_rotation": src_outputs["spacemouse_rotation"],
            },
            out,
        )

        assert np.allclose(np.asarray(out["base_command"][0]), 0.0)
