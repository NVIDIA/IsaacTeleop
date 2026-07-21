# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared pipeline and visualization helpers for the record / replay / live scripts.

Pipeline builders: ``build_hand_pipeline``, ``build_controller_pipeline``,
``build_full_body_pipeline``.

Viz classes (used by replay_* and live_* scripts): ``HandViz``,
``ControllerViz``, ``FullBodyViz``.

Rendering helpers: ``HandJoints``, ``HAND_BONES``, ``BODY_BONES``.
"""

import argparse
import contextlib
import os

import numpy as np
import viser

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    HandsSource,
)
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OutputCombiner,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    NUM_HAND_JOINTS,
    BoolType,
    HandInput,
    HandInputIndex,
)
from isaacteleop.retargeting_engine.tensor_types.indices import (
    BodyJointIndex,
    ControllerInputIndex,
)
from isaacteleop.retargeting_engine.tensor_types.ndarray_types import (
    DLDataType,
    NDArrayType,
)


_ZERO_POSITIONS = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)


# ---------------------------------------------------------------------------
# CloudXR launcher helpers shared across record / live scripts
# ---------------------------------------------------------------------------


def add_cloudxr_arguments(parser: argparse.ArgumentParser) -> None:
    """Register CloudXR launcher arguments on ``parser``.

    Adds ``--launch-cloudxr-runtime`` (default: true) and
    ``--no-launch-cloudxr-runtime`` to skip launching when a CloudXR instance
    is already running (e.g. from GR00T-WholeBodyControl).  Also registers
    ``--accept-eula`` and ``--cloudxr-install-dir`` for when the launcher is
    active.  Source the CloudXR env file before running without the launcher::

        source ~/.cloudxr/run/cloudxr.env
    """
    parser.add_argument(
        "--launch-cloudxr-runtime",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Launch the CloudXR runtime and WSS proxy before connecting "
            "(default: true). Pass --no-launch-cloudxr-runtime to connect "
            "to an already-running instance (source ~/.cloudxr/run/cloudxr.env first)."
        ),
    )
    parser.add_argument(
        "--accept-eula",
        action="store_true",
        help="Accept the NVIDIA CloudXR EULA non-interactively (required on first launch).",
    )
    parser.add_argument(
        "--cloudxr-install-dir",
        default=os.path.expanduser("~/.cloudxr"),
        metavar="PATH",
        help="CloudXR install directory (default: ~/.cloudxr).",
    )


def cloudxr_launch_context(
    args: argparse.Namespace,
) -> contextlib.AbstractContextManager:
    """Return a context manager that launches CloudXR or is a no-op.

    When ``args.launch_cloudxr_runtime`` is true (the default), returns a
    :class:`~isaacteleop.cloudxr.CloudXRLauncher` context manager that starts
    the runtime and WSS proxy.  When false, returns
    :func:`contextlib.nullcontext` so the caller can always write::

        with cloudxr_launch_context(args) as launcher:
            if launcher is not None:
                print(f"WSS log: {launcher.wss_log_path}")
            ...
    """
    if not args.launch_cloudxr_runtime:
        return contextlib.nullcontext(None)
    return CloudXRLauncher(
        install_dir=args.cloudxr_install_dir,
        accept_eula=args.accept_eula,
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


def _positions_group(name: str) -> TensorGroupType:
    return TensorGroupType(
        name,
        [
            NDArrayType(
                "positions",
                shape=(NUM_HAND_JOINTS, 3),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            )
        ],
    )


class HandJoints(BaseRetargeter):
    """Passes hand joint positions + validity through for downstream consumers.

    Zero-fills positions when a hand is not tracked so downstream code can read
    a fixed-shape array every frame.
    """

    def input_spec(self):
        return {
            HandsSource.LEFT: OptionalType(HandInput()),
            HandsSource.RIGHT: OptionalType(HandInput()),
        }

    def output_spec(self):
        return {
            "left_positions": _positions_group("left_positions"),
            "right_positions": _positions_group("right_positions"),
            "left_valid": TensorGroupType("left_valid", [BoolType("v")]),
            "right_valid": TensorGroupType("right_valid", [BoolType("v")]),
        }

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        for side, key in (("left", HandsSource.LEFT), ("right", HandsSource.RIGHT)):
            optional_hand = inputs[key]
            if optional_hand.is_none:
                outputs[f"{side}_valid"][0] = False
                outputs[f"{side}_positions"][0] = _ZERO_POSITIONS.copy()
            else:
                outputs[f"{side}_valid"][0] = True
                outputs[f"{side}_positions"][0] = np.asarray(
                    optional_hand[HandInputIndex.JOINT_POSITIONS],
                    dtype=np.float32,
                )


def build_hand_pipeline():
    hands = HandsSource(name=HANDS_CHANNEL)
    joints = HandJoints(name="hand_joints")
    return joints.connect(
        {
            HandsSource.LEFT: hands.output(HandsSource.LEFT),
            HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
        }
    )


def build_controller_pipeline():
    controllers = ControllersSource(name="controllers")
    return OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
        }
    )


def build_full_body_pipeline():
    controllers = ControllersSource(name="controllers")
    full_body = FullBodySource(name="full_body")
    return OutputCombiner(
        {
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


# ---------------------------------------------------------------------------
# Shared viser visualization classes
# ---------------------------------------------------------------------------


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
