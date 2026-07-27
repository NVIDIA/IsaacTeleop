# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""DeviceIO-to-viser helpers for the live human-tracking viewer.

Pipeline builder: ``build_all_human_pipeline``.

Viz classes: ``HandViz``, ``ControllerViz``, ``FullBodyViz``, ``HeadViz``,
``HumanDeviceIOViz``.

Rendering helpers: ``HAND_BONES``, ``BODY_BONES``, ``controller_state``.
"""

import numpy as np
import viser

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    HandsSource,
    HeadSource,
)
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.retargeting_engine.tensor_types import HandInputIndex
from isaacteleop.retargeting_engine.tensor_types.indices import (
    BodyJointIndex,
    ControllerInputIndex,
    FullBodyInputIndex,
    HeadPoseIndex,
)

HANDS_CHANNEL = "hands"
BODY_JOINT_NAMES = [joint.name for joint in BodyJointIndex]

# ---------------------------------------------------------------------------
# Color palette shared across all viz scripts
# ---------------------------------------------------------------------------

LEFT_COLOR: tuple[float, float, float] = (0.25, 0.85, 0.35)
RIGHT_COLOR: tuple[float, float, float] = (0.35, 0.55, 0.95)
INVALID_COLOR: tuple[float, float, float] = (1.0, 0.0, 0.0)
TRACKED_COLOR: tuple[float, float, float] = (0.25, 0.85, 0.35)


def build_all_human_pipeline():
    """Wire every human-related DeviceIO source into one pipeline."""
    hands = HandsSource(name=HANDS_CHANNEL)
    head = HeadSource(name="head")
    controllers = ControllersSource(name="controllers")
    full_body = FullBodySource(name="full_body")
    return OutputCombiner(
        {
            "hand_left": hands.output(HandsSource.LEFT),
            "hand_right": hands.output(HandsSource.RIGHT),
            "head": head.output("head"),
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
            "full_body": full_body.output(FullBodySource.FULL_BODY),
        }
    )


# PICO body-joint connectivity (parent → child) for skeleton rendering.
# Indices follow BodyJointIndex: 0=PELVIS, 1/2=LEFT/RIGHT_HIP, 3/6/9=SPINE1/2/3,
# 4/5=LEFT/RIGHT_KNEE, 7/8=LEFT/RIGHT_ANKLE, 10/11=LEFT/RIGHT_FOOT, 12=NECK,
# 13/14=LEFT/RIGHT_COLLAR, 15=HEAD, 16/17=LEFT/RIGHT_SHOULDER,
# 18/19=LEFT/RIGHT_ELBOW, 20/21=LEFT/RIGHT_WRIST, 22/23=LEFT/RIGHT_HAND — 24 total.
BODY_BONES: tuple[tuple[int, int], ...] = (
    # Trunk and spine
    (0, 1),
    (0, 2),
    (0, 3),
    (3, 6),
    (6, 9),
    (9, 12),
    (12, 15),
    # Left leg
    (1, 4),
    (4, 7),
    (7, 10),
    # Right leg
    (2, 5),
    (5, 8),
    (8, 11),
    # Left arm
    (12, 13),
    (13, 16),
    (16, 18),
    (18, 20),
    (20, 22),
    # Right arm
    (12, 14),
    (14, 17),
    (17, 19),
    (19, 21),
    (21, 23),
)


# OpenXR hand-joint connectivity (parent → child) for skeleton rendering.
# Indices follow XR_HAND_JOINT_*_EXT: 0=PALM, 1=WRIST, thumb has 4 joints
# (no intermediate), the other 4 fingers have 5 joints each — 26 total.
HAND_BONES: tuple[tuple[int, int], ...] = (
    # Thumb
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),
    # Index
    (1, 6),
    (6, 7),
    (7, 8),
    (8, 9),
    (9, 10),
    # Middle
    (1, 11),
    (11, 12),
    (12, 13),
    (13, 14),
    (14, 15),
    # Ring
    (1, 16),
    (16, 17),
    (17, 18),
    (18, 19),
    (19, 20),
    # Little
    (1, 21),
    (21, 22),
    (22, 23),
    (23, 24),
    (24, 25),
)


def _bone_segments(positions: np.ndarray) -> np.ndarray:
    """Return (N, 2, 3) segment array for the parent→child hand bones."""
    return np.stack(
        [np.stack([positions[a], positions[b]], axis=0) for a, b in HAND_BONES],
        axis=0,
    ).astype(np.float32)


def _valid_bone_segments(positions: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Return (N, 2, 3) segment array for body bones whose both endpoints are valid."""
    segments: list[np.ndarray] = []
    for a, b in BODY_BONES:
        if valid[a] and valid[b]:
            segments.append(np.stack([positions[a], positions[b]], axis=0))
    if not segments:
        return np.zeros((0, 2, 3), dtype=np.float32)
    return np.stack(segments, axis=0).astype(np.float32)


def _segment(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    return np.stack([start, end], axis=0).astype(np.float32)


def controller_state(controller) -> dict:
    """Extract a plain-dict snapshot from a controller TensorGroup."""
    if controller.is_none:
        return {
            "aim_pos": None,
            "grip_pos": None,
            "aim_valid": False,
            "grip_valid": False,
            "trigger": 0.0,
            "squeeze": 0.0,
            "thumbstick_xy": (0.0, 0.0),
            "primary_click": False,
            "secondary_click": False,
            "thumbstick_click": False,
            "menu_click": False,
            "tracked": False,
        }

    aim_valid = bool(controller[ControllerInputIndex.AIM_IS_VALID])
    grip_valid = bool(controller[ControllerInputIndex.GRIP_IS_VALID])
    return {
        "aim_pos": np.asarray(
            controller[ControllerInputIndex.AIM_POSITION], dtype=np.float32
        ),
        "grip_pos": np.asarray(
            controller[ControllerInputIndex.GRIP_POSITION], dtype=np.float32
        ),
        "aim_valid": aim_valid,
        "grip_valid": grip_valid,
        "trigger": float(controller[ControllerInputIndex.TRIGGER_VALUE]),
        "squeeze": float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
        "thumbstick_xy": (
            float(controller[ControllerInputIndex.THUMBSTICK_X]),
            float(controller[ControllerInputIndex.THUMBSTICK_Y]),
        ),
        "primary_click": float(controller[ControllerInputIndex.PRIMARY_CLICK]) > 0.5,
        "secondary_click": float(controller[ControllerInputIndex.SECONDARY_CLICK])
        > 0.5,
        "thumbstick_click": float(controller[ControllerInputIndex.THUMBSTICK_CLICK])
        > 0.5,
        "menu_click": float(controller[ControllerInputIndex.MENU_CLICK]) > 0.5,
        "tracked": aim_valid or grip_valid,
    }


class HandViz:
    """Per-hand viser handles (joint cloud + skeleton segments)."""

    def __init__(
        self,
        server: viser.ViserServer,
        name: str,
        color: tuple[float, float, float],
    ):
        self.color = np.array(color, dtype=np.float32)
        zero_pts = np.zeros((26, 3), dtype=np.float32)
        zero_segs = np.zeros((len(HAND_BONES), 2, 3), dtype=np.float32)

        self.points = server.scene.add_point_cloud(
            name=f"/{name}/joints",
            points=zero_pts,
            colors=np.tile(self.color, (26, 1)),
            point_size=0.008,
        )
        self.bones = server.scene.add_line_segments(
            name=f"/{name}/bones",
            points=zero_segs,
            colors=np.tile(self.color, (len(HAND_BONES), 2, 1)),
            line_width=2.0,
        )

    def update(self, positions: np.ndarray, valid: bool) -> None:
        if valid:
            self.points.points = positions.astype(np.float32)
            self.points.colors = np.tile(self.color, (positions.shape[0], 1))
            self.bones.points = _bone_segments(positions)
        else:
            zero_pts = np.zeros_like(positions, dtype=np.float32)
            self.points.points = zero_pts
            self.points.colors = np.tile(INVALID_COLOR, (positions.shape[0], 1))
            self.bones.points = np.zeros((len(HAND_BONES), 2, 3), dtype=np.float32)


class ControllerViz:
    """Per-controller viser handles (3D pose + live input-state HUD)."""

    def __init__(
        self,
        server: viser.ViserServer,
        name: str,
        color: tuple[float, float, float],
    ):
        self.color = np.array(color, dtype=np.float32)
        zero_pt = np.zeros((1, 3), dtype=np.float32)
        zero_seg = np.zeros((0, 2, 3), dtype=np.float32)
        zero_seg_colors = np.zeros((0, 2, 3), dtype=np.float32)

        self.aim = server.scene.add_point_cloud(
            name=f"/{name}/aim",
            points=zero_pt,
            colors=np.tile(self.color, (1, 1)),
            point_size=0.015,
        )
        self.grip = server.scene.add_point_cloud(
            name=f"/{name}/grip",
            points=zero_pt,
            colors=np.tile(self.color, (1, 1)),
            point_size=0.015,
        )
        self.ray = server.scene.add_line_segments(
            name=f"/{name}/ray",
            points=zero_seg,
            colors=zero_seg_colors,
            line_width=2.0,
        )

        with server.gui.add_folder(name):
            self.hud_tracking = server.gui.add_checkbox("tracked", False, disabled=True)
            self.hud_aim_valid = server.gui.add_checkbox(
                "aim_valid", False, disabled=True
            )
            self.hud_grip_valid = server.gui.add_checkbox(
                "grip_valid", False, disabled=True
            )
            self.hud_stick = server.gui.add_vector2(
                "thumbstick_xy",
                initial_value=(0.0, 0.0),
                min=(-1.0, -1.0),
                max=(1.0, 1.0),
                disabled=True,
            )
            self.hud_trigger_value = server.gui.add_number(
                "trigger",
                initial_value=0.0,
                min=0.0,
                max=1.0,
                step=0.01,
                disabled=True,
            )
            self.hud_trigger = server.gui.add_progress_bar(0.0)
            self.hud_squeeze_value = server.gui.add_number(
                "squeeze",
                initial_value=0.0,
                min=0.0,
                max=1.0,
                step=0.01,
                disabled=True,
            )
            self.hud_squeeze = server.gui.add_progress_bar(0.0)
            self.hud_primary = server.gui.add_checkbox(
                "primary_click", False, disabled=True
            )
            self.hud_secondary = server.gui.add_checkbox(
                "secondary_click", False, disabled=True
            )
            self.hud_stick_click = server.gui.add_checkbox(
                "thumbstick_click", False, disabled=True
            )
            self.hud_menu_click = server.gui.add_checkbox(
                "menu_click", False, disabled=True
            )

    def update(self, state: dict) -> None:
        aim_valid: bool = state["aim_valid"]
        grip_valid: bool = state["grip_valid"]
        aim_pos: np.ndarray | None = state["aim_pos"]
        grip_pos: np.ndarray | None = state["grip_pos"]

        self.hud_tracking.value = state["tracked"]
        self.hud_aim_valid.value = aim_valid
        self.hud_grip_valid.value = grip_valid
        self.hud_stick.value = state["thumbstick_xy"]
        self.hud_trigger.value = max(0.0, min(1.0, state["trigger"]))
        self.hud_trigger_value.value = state["trigger"]
        self.hud_squeeze.value = max(0.0, min(1.0, state["squeeze"]))
        self.hud_squeeze_value.value = state["squeeze"]
        self.hud_primary.value = state["primary_click"]
        self.hud_secondary.value = state["secondary_click"]
        self.hud_stick_click.value = state["thumbstick_click"]
        self.hud_menu_click.value = state["menu_click"]

        if aim_valid and aim_pos is not None:
            self.aim.points = aim_pos.reshape(1, 3).astype(np.float32)
            self.aim.colors = np.tile(self.color, (1, 1))
        else:
            self.aim.points = np.zeros((1, 3), dtype=np.float32)
            self.aim.colors = np.tile(INVALID_COLOR, (1, 1))

        if grip_valid and grip_pos is not None:
            self.grip.points = grip_pos.reshape(1, 3).astype(np.float32)
            self.grip.colors = np.tile(self.color, (1, 1))
        else:
            self.grip.points = np.zeros((1, 3), dtype=np.float32)
            self.grip.colors = np.tile(INVALID_COLOR, (1, 1))

        if aim_valid and grip_valid and aim_pos is not None and grip_pos is not None:
            seg = _segment(grip_pos, aim_pos).reshape(1, 2, 3)
            self.ray.points = seg
            self.ray.colors = np.tile(self.color, (1, 2, 1))
        else:
            self.ray.points = np.zeros((0, 2, 3), dtype=np.float32)
            self.ray.colors = np.zeros((0, 2, 3), dtype=np.float32)


class FullBodyViz:
    """Viser handles for full-body skeleton (joint cloud + skeleton segments)."""

    def __init__(self, server: viser.ViserServer):
        self.color = np.array(TRACKED_COLOR, dtype=np.float32)
        zero_pts = np.zeros((len(BODY_JOINT_NAMES), 3), dtype=np.float32)
        zero_segs = np.zeros((0, 2, 3), dtype=np.float32)

        self.points = server.scene.add_point_cloud(
            name="/full_body/joints",
            points=zero_pts,
            colors=np.tile(self.color, (len(BODY_JOINT_NAMES), 1)),
            point_size=0.01,
        )
        self.bones = server.scene.add_line_segments(
            name="/full_body/bones",
            points=zero_segs,
            colors=np.zeros((0, 2, 3), dtype=np.float32),
            line_width=2.0,
        )

    def update(self, positions: np.ndarray | None, valid: np.ndarray | None) -> None:
        if positions is None or valid is None:
            zero_pts = np.zeros((len(BODY_JOINT_NAMES), 3), dtype=np.float32)
            self.points.points = zero_pts
            self.points.colors = np.tile(INVALID_COLOR, (len(BODY_JOINT_NAMES), 1))
            self.bones.points = np.zeros((0, 2, 3), dtype=np.float32)
            self.bones.colors = np.zeros((0, 2, 3), dtype=np.float32)
            return

        positions = positions.astype(np.float32)
        valid_bool = valid.astype(bool)
        self.points.points = positions

        point_colors = np.tile(self.color, (positions.shape[0], 1))
        point_colors[~valid_bool] = INVALID_COLOR
        self.points.colors = point_colors

        segs = _valid_bone_segments(positions, valid_bool)
        self.bones.points = segs
        self.bones.colors = np.tile(self.color, (segs.shape[0], 2, 1))


def _xyzw_to_wxyz(orientation: np.ndarray) -> tuple[float, float, float, float]:
    quat = np.asarray(orientation, dtype=np.float32).reshape(4)
    return (float(quat[3]), float(quat[0]), float(quat[1]), float(quat[2]))


class HeadViz:
    """Head pose frame (hidden when tracking is inactive)."""

    def __init__(
        self,
        server: viser.ViserServer,
        name: str = "head",
        axes_length: float = 0.12,
    ):
        self.frame = server.scene.add_frame(
            name=f"/{name}/frame",
            axes_length=axes_length,
            axes_radius=0.004,
            visible=False,
        )

    def update_if_active(self, head) -> bool:
        if head.is_none or not bool(head[HeadPoseIndex.IS_VALID]):
            self.frame.visible = False
            return False

        position = np.asarray(head[HeadPoseIndex.POSITION], dtype=np.float32)
        orientation = np.asarray(head[HeadPoseIndex.ORIENTATION], dtype=np.float32)
        self.frame.position = (
            float(position[0]),
            float(position[1]),
            float(position[2]),
        )
        self.frame.wxyz = _xyzw_to_wxyz(orientation)
        self.frame.visible = True
        return True


class HumanDeviceIOViz:
    """Aggregate viser handles for all human DeviceIO trackers.

    Inactive or absent trackers are hidden instead of drawn in the invalid color.
    """

    def __init__(self, server: viser.ViserServer):
        self.hand_left = HandViz(server, "hand_left", LEFT_COLOR)
        self.hand_right = HandViz(server, "hand_right", RIGHT_COLOR)
        self.head = HeadViz(server)
        self.controller_left = ControllerViz(server, "controller_left", LEFT_COLOR)
        self.controller_right = ControllerViz(server, "controller_right", RIGHT_COLOR)
        self.full_body = FullBodyViz(server)

    def _update_hand_if_active(self, viz: HandViz, hand) -> bool:
        if hand.is_none:
            viz.points.visible = False
            viz.bones.visible = False
            return False

        positions = np.asarray(hand[HandInputIndex.JOINT_POSITIONS], dtype=np.float32)
        viz.points.visible = True
        viz.bones.visible = True
        viz.update(positions, valid=True)
        return True

    def _update_controller_if_active(self, viz: ControllerViz, controller) -> bool:
        state = controller_state(controller)
        if not state["tracked"]:
            viz.aim.visible = False
            viz.grip.visible = False
            viz.ray.visible = False
            viz.update(state)
            return False

        viz.aim.visible = True
        viz.grip.visible = True
        viz.ray.visible = True
        viz.update(state)
        return True

    def _update_full_body_if_active(self, full_body) -> tuple[bool, int]:
        if full_body.is_none:
            self.full_body.points.visible = False
            self.full_body.bones.visible = False
            return False, 0

        positions = np.asarray(
            full_body[FullBodyInputIndex.JOINT_POSITIONS], dtype=np.float32
        )
        valid = np.asarray(full_body[FullBodyInputIndex.JOINT_VALID], dtype=np.uint8)
        n_valid = int(np.count_nonzero(valid))
        if n_valid == 0:
            self.full_body.points.visible = False
            self.full_body.bones.visible = False
            return False, 0

        self.full_body.points.visible = True
        self.full_body.bones.visible = True
        self.full_body.update(positions, valid)
        return True, n_valid

    def update(self, result) -> dict[str, bool | int]:
        """Update every tracker; hide inactive ones. Returns active flags."""
        full_body_active, full_body_joints = self._update_full_body_if_active(
            result["full_body"]
        )
        return {
            "hand_left": self._update_hand_if_active(
                self.hand_left, result["hand_left"]
            ),
            "hand_right": self._update_hand_if_active(
                self.hand_right, result["hand_right"]
            ),
            "head": self.head.update_if_active(result["head"]),
            "controller_left": self._update_controller_if_active(
                self.controller_left, result["controller_left"]
            ),
            "controller_right": self._update_controller_if_active(
                self.controller_right, result["controller_right"]
            ),
            "full_body_active": full_body_active,
            "full_body_joints": full_body_joints,
        }
