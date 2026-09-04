# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal Isaac Lab scene for AVP + MANUS teleop on G1-Wuji.

Run this script with an Isaac Sim / Isaac Lab Python environment. It intentionally
keeps the simulation side small: a ground plane, a light, the selected G1 USD,
and live hand joint targets from ``TeleopMain``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .config import default_config_path, example_path, load_yaml_file
from .input_stream import TeleopMain
from .robot import (
    AvpRobotFrameBinding,
    HandTargetPostProcessor,
    WujiHandTargetBackend,
    as_torch,
    avp_frame_binding_runtime_config,
    matrix_to_quat_xyzw,
    normalize_quat_xyzw,
    openxr_pose_to_isaac_pose,
    robot_profile_from_config,
    wuji_hand_runtime_config,
)
from .scene import (
    G1WujiSceneConfig,
    design_g1_wuji_scene,
)


ARM_JOINTS = {
    "left": (
        "left_shoulder_pitch_joint",
        "left_shoulder_roll_joint",
        "left_shoulder_yaw_joint",
        "left_elbow_joint",
        "left_wrist_roll_joint",
        "left_wrist_pitch_joint",
        "left_wrist_yaw_joint",
    ),
    "right": (
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_joint",
        "right_wrist_roll_joint",
        "right_wrist_pitch_joint",
        "right_wrist_yaw_joint",
    ),
}


@dataclass(frozen=True)
class HeadViewCameraConfig:
    enabled: bool = True
    activate_on_calibration: bool = True
    prim_path: str = "/World/TeleopTargets/HeadViewCamera"
    head_link_prim_path: str = "/World/G1Wuji/torso_link/head_link"
    translation_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation_offset_rpy_deg: tuple[float, float, float] = (90.0, 0.0, 90.0)
    horizontal_aperture_mm: float = 20.955
    focal_length_mm: float = 18.14756
    clipping_range_m: tuple[float, float] = (0.01, 1000.0)


@dataclass(frozen=True)
class ThirdViewpointConfig:
    relative_position_m: tuple[float, float, float] = (0.0, -1.2, 0.55)


class HeadViewCameraController:
    """Drive a viewport camera from the robot head pose after AVP calibration."""

    def __init__(
        self,
        *,
        stage: Any,
        UsdGeom: Any,
        Gf: Any,
        viewport_api: Any,
        config: HeadViewCameraConfig,
        head_link_prim: Any | None,
        avp_frame_binding: Any | None,
    ) -> None:
        self._config = config
        self._viewport_api = viewport_api
        self._UsdGeom = UsdGeom
        self._Gf = Gf
        self._head_link_prim = head_link_prim
        self._avp_frame_binding = avp_frame_binding
        self._active = False
        self._announced_missing_head = False
        self._orientation_offset_quat = self._orientation_offset_quatd(config)

        camera = UsdGeom.Camera.Define(stage, config.prim_path)
        self._camera_prim = camera.GetPrim()
        self._camera_xform = UsdGeom.Xformable(self._camera_prim)
        self._translate_op = self._camera_xform.AddTranslateOp()
        # USD xform op value types are strict. Head prim world rotations come back as
        # GfQuatd here, so keep the camera orient op in double precision as well.
        self._orient_op = self._camera_xform.AddOrientOp(
            precision=UsdGeom.XformOp.PrecisionDouble
        )
        self._scale_op = self._camera_xform.AddScaleOp()
        self._camera_path = str(self._camera_prim.GetPath())

        camera.GetHorizontalApertureAttr().Set(float(config.horizontal_aperture_mm))
        camera.GetFocalLengthAttr().Set(float(config.focal_length_mm))
        camera.GetClippingRangeAttr().Set(
            Gf.Vec2f(
                float(config.clipping_range_m[0]),
                float(config.clipping_range_m[1]),
            )
        )
        self._scale_op.Set(Gf.Vec3f(1.0, 1.0, 1.0))

    @property
    def camera_path(self) -> str:
        return self._camera_path

    def activate(self) -> None:
        if self._viewport_api is None:
            return
        self._viewport_api.camera_path = self._camera_path
        self._active = True

    def deactivate(self) -> None:
        self._active = False

    def update(self, *, xform_cache: Any) -> None:
        head_link_prim = self._head_link_prim
        if head_link_prim is None or xform_cache is None:
            if not self._announced_missing_head:
                print(
                    "Head view camera is enabled but no robot head prim is available; "
                    "camera updates are disabled.",
                    flush=True,
                )
                self._announced_missing_head = True
            return

        xform_cache.Clear()
        world_transform = xform_cache.GetLocalToWorldTransform(head_link_prim)
        world_translation = world_transform.ExtractTranslation()
        world_rotation = world_transform.ExtractRotationQuat()
        camera_base_rotation = world_rotation * self._orientation_offset_quat
        camera_rotation = self._apply_head_pose_delta(camera_base_rotation)

        offset = self._config.translation_offset_m
        offset_vec = self._Gf.Vec3d(
            float(offset[0]), float(offset[1]), float(offset[2])
        )
        camera_translation = world_translation + world_transform.TransformDir(
            offset_vec
        )

        self._translate_op.Set(camera_translation)
        self._orient_op.Set(camera_rotation)

    def _apply_head_pose_delta(self, base_rotation: Any) -> Any:
        avp_frame_binding = self._avp_frame_binding
        if avp_frame_binding is None or not avp_frame_binding.calibrated:
            return base_rotation
        tilt_delta_rot = avp_frame_binding.latest_head_tilt_delta_rot()
        camera_rotation = base_rotation
        if tilt_delta_rot is not None:
            tilt_delta_quat = self._matrix3_to_quatd(tilt_delta_rot)
            camera_rotation = tilt_delta_quat * camera_rotation
        return camera_rotation

    def _orientation_offset_quatd(self, config: HeadViewCameraConfig) -> Any:
        roll_deg, pitch_deg, yaw_deg = config.orientation_offset_rpy_deg
        roll_rad = np.deg2rad(float(roll_deg))
        pitch_rad = np.deg2rad(float(pitch_deg))
        yaw_rad = np.deg2rad(float(yaw_deg))

        cr = np.cos(roll_rad * 0.5)
        sr = np.sin(roll_rad * 0.5)
        cp = np.cos(pitch_rad * 0.5)
        sp = np.sin(pitch_rad * 0.5)
        cy = np.cos(yaw_rad * 0.5)
        sy = np.sin(yaw_rad * 0.5)

        quat_xyzw = normalize_quat_xyzw(
            (
                sr * cp * cy - cr * sp * sy,
                cr * sp * cy + sr * cp * sy,
                cr * cp * sy - sr * sp * cy,
                cr * cp * cy + sr * sp * sy,
            )
        )
        return self._Gf.Quatd(
            float(quat_xyzw[3]),
            self._Gf.Vec3d(
                float(quat_xyzw[0]),
                float(quat_xyzw[1]),
                float(quat_xyzw[2]),
            ),
        )

    def _matrix3_to_quatd(self, matrix: np.ndarray) -> Any:
        quat_xyzw = normalize_quat_xyzw(
            matrix_to_quat_xyzw(np.asarray(matrix, dtype=np.float64))
        )
        return self._Gf.Quatd(
            float(quat_xyzw[3]),
            self._Gf.Vec3d(
                float(quat_xyzw[0]),
                float(quat_xyzw[1]),
                float(quat_xyzw[2]),
            ),
        )


class ThirdViewpointController:
    """Drive a right-side viewport viewpoint from the robot reference pose."""

    _VIEWPOINT_PATH = "/OmniverseKit_Persp"
    _WINDOW_TITLE = "G1-Wuji Third View"

    def __init__(
        self,
        *,
        Gf: Any,
        ViewportManager: Any,
        viewport_utility: Any,
        ui: Any,
        config: ThirdViewpointConfig,
        reference_prim: Any,
        main_viewport_api: Any,
        main_camera_path: str | None,
        status_label: str,
    ) -> None:
        self._Gf = Gf
        self._ViewportManager = ViewportManager
        self._viewport_utility = viewport_utility
        self._ui = ui
        self._config = config
        self._reference_prim = reference_prim
        self._main_viewport_api = main_viewport_api
        self._main_camera_path = (
            None if main_camera_path is None else str(main_camera_path)
        )
        self._status_label = status_label
        self._window = None
        self._viewport_api = None
        self._active = False
        self._layout_requested = False

    def activate(self, *, xform_cache: Any) -> None:
        if self._active:
            return
        if self._ensure_window() is None:
            return
        self._set_window_camera()
        self._set_initial_view(xform_cache=xform_cache)
        self._set_main_camera()
        self._active = True

    def deactivate(self) -> None:
        self._active = False
        if self._window is not None:
            self._window.visible = False

    def _set_initial_view(self, *, xform_cache: Any) -> None:
        xform_cache.Clear()
        world_transform = xform_cache.GetLocalToWorldTransform(self._reference_prim)
        target = world_transform.ExtractTranslation()
        offset = self._config.relative_position_m
        eye = target + world_transform.TransformDir(
            self._Gf.Vec3d(float(offset[0]), float(offset[1]), float(offset[2]))
        )
        self._ViewportManager.set_camera_view(
            self._VIEWPOINT_PATH,
            eye=self._vec3_to_list(eye),
            target=self._vec3_to_list(target),
        )

    def _ensure_window(self) -> Any:
        if self._window is not None:
            self._window.visible = True
            return self._window

        self._window = self._viewport_utility.create_viewport_window(
            self._WINDOW_TITLE,
            width=1280,
            height=720,
            camera_path=self._VIEWPOINT_PATH,
        )
        if self._window is None:
            print(
                f"[{self._status_label}] failed to create third viewpoint window.",
                flush=True,
            )
            return None

        self._viewport_api = self._window.viewport_api
        self._set_window_camera()
        self._window.visible = True
        self._dock_to_main_viewport_async()
        return self._window

    def _dock_to_main_viewport_async(self) -> None:
        window = self._window
        if window is None or self._layout_requested:
            return
        self._layout_requested = True

        async def dock_window() -> None:
            import omni.kit.app

            await omni.kit.app.get_app().next_update_async()
            target_window = self._ui.Workspace.get_window("Viewport")
            if target_window is not None and window is not None:
                window.dock_in(target_window, self._ui.DockPosition.RIGHT, 0.5)
            self._set_window_camera()
            self._set_main_camera()

        asyncio.ensure_future(dock_window())

    def _set_main_camera(self) -> None:
        if self._main_viewport_api is None or not self._main_camera_path:
            return
        self._main_viewport_api.camera_path = self._main_camera_path

    def _set_window_camera(self) -> None:
        if self._viewport_api is None:
            return
        self._viewport_api.camera_path = self._VIEWPOINT_PATH

    def _vec3_to_list(self, value: Any) -> list[float]:
        return [float(value[0]), float(value[1]), float(value[2])]


def _head_view_camera_config(config: Mapping[str, Any]) -> HeadViewCameraConfig:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    camera_config = robot_config.get("head_view_camera", {})
    if camera_config is None:
        camera_config = {}
    if not isinstance(camera_config, Mapping):
        raise ValueError("Config field 'robot.head_view_camera' must be a mapping")

    prim_path = str(
        camera_config.get("prim_path", "/World/TeleopTargets/HeadViewCamera")
    ).strip()
    if not prim_path:
        raise ValueError(
            "Config field 'robot.head_view_camera.prim_path' must be non-empty"
        )
    head_link_prim_path = str(
        camera_config.get(
            "head_link_prim_path",
            "/World/G1Wuji/torso_link/head_link",
        )
    ).strip()
    if not head_link_prim_path:
        raise ValueError(
            "Config field 'robot.head_view_camera.head_link_prim_path' must be non-empty"
        )

    return HeadViewCameraConfig(
        enabled=bool(camera_config.get("enabled", True)),
        activate_on_calibration=bool(
            camera_config.get("activate_on_calibration", True)
        ),
        prim_path=prim_path,
        head_link_prim_path=head_link_prim_path,
        translation_offset_m=_float_tuple(
            camera_config.get("translation_offset_m"),
            name="robot.head_view_camera.translation_offset_m",
            length=3,
            default=(0.0, 0.0, 0.0),
        ),
        orientation_offset_rpy_deg=_float_tuple(
            camera_config.get("orientation_offset_rpy_deg"),
            name="robot.head_view_camera.orientation_offset_rpy_deg",
            length=3,
            default=(90.0, 0.0, 90.0),
        ),
        horizontal_aperture_mm=float(
            camera_config.get("horizontal_aperture_mm", 20.955)
        ),
        focal_length_mm=float(camera_config.get("focal_length_mm", 18.14756)),
        clipping_range_m=_float_tuple(
            camera_config.get("clipping_range_m"),
            name="robot.head_view_camera.clipping_range_m",
            length=2,
            default=(0.01, 1000.0),
        ),
    )


def _third_viewpoint_config(config: Mapping[str, Any]) -> ThirdViewpointConfig | None:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")
    if "third_viewpoint" not in robot_config:
        return None

    viewpoint_config = robot_config.get("third_viewpoint", {})
    if viewpoint_config is None:
        viewpoint_config = {}
    if not isinstance(viewpoint_config, Mapping):
        raise ValueError("Config field 'robot.third_viewpoint' must be a mapping")

    return ThirdViewpointConfig(
        relative_position_m=_float_tuple(
            viewpoint_config.get("relative_position_m"),
            name="robot.third_viewpoint.relative_position_m",
            length=3,
            default=(0.0, -1.2, 0.55),
        )
    )


def _hide_third_viewpoint_window(viewport_utility: Any) -> None:
    window = viewport_utility.get_active_viewport_window(
        window_name=ThirdViewpointController._WINDOW_TITLE
    )
    if window is not None:
        window.visible = False


@dataclass(frozen=True)
class ArmIkSideConfig:
    body_name: str
    body_offset_pos: tuple[float, float, float]
    body_offset_quat_xyzw: tuple[float, float, float, float]
    target_orientation_correction_quat_xyzw: tuple[float, float, float, float]
    joint_names: tuple[str, ...]


@dataclass(frozen=True)
class ArmIkRuntimeConfig:
    status_label: str = "teleop"
    enabled: bool = True
    pose_scale: float = 1.0
    pose_z_offset: float = 0.0
    command_type: str = "pose"
    startup_relative_position: bool = True
    startup_relative_orientation: bool = True
    position_error_scale: float = 1.0
    orientation_error_scale: float = 0.35
    position_deadband_m: float = 0.003
    orientation_deadband_rad: float = 0.06
    ik_method: str = "dls"
    damping: float = 0.05
    smoothing_alpha: float = 0.35
    clamp_to_joint_limits: bool = True
    sides: dict[str, ArmIkSideConfig] = field(default_factory=dict)


def _default_config_path() -> Path:
    return default_config_path()


def _robot_initial_world_position(
    config: Mapping[str, Any],
) -> tuple[float, float, float]:
    robot_config = config.get("robot", {})
    if robot_config is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    return _float_tuple(
        robot_config.get("initial_world_position"),
        name="robot.initial_world_position",
        length=3,
        default=(0.0, 0.0, 0.0),
    )


def _robot_initial_world_orientation_xyzw(
    config: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    robot_config = config.get("robot", {})
    if robot_config is None:
        return (0.0, 0.0, 0.0, 1.0)
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    raw_quat = robot_config.get("initial_world_orientation_xyzw")
    quat = _float_tuple(
        raw_quat,
        name="robot.initial_world_orientation_xyzw",
        length=4,
        default=(0.0, 0.0, 0.0, 1.0),
    )
    norm = sum(value * value for value in quat) ** 0.5
    if norm < 1.0e-8:
        raise ValueError(
            "Config field 'robot.initial_world_orientation_xyzw' must be non-zero"
        )
    return tuple(value / norm for value in quat)


def _float_tuple(
    values: Any,
    *,
    name: str,
    length: int,
    default: Sequence[float],
) -> tuple[float, ...]:
    raw = default if values is None else values
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"Config field {name!r} must be a {length}-element sequence")
    if len(raw) != length:
        raise ValueError(f"Config field {name!r} must contain exactly {length} values")
    return tuple(float(value) for value in raw)


def _arm_ik_runtime_config(config: Mapping[str, Any]) -> ArmIkRuntimeConfig:
    profile = robot_profile_from_config(config)
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    # Keep the arm IK body bindings pinned in code rather than mirroring them in
    # the teleop YAML. These offsets are asset-specific and tuned together.
    sides = {
        "left": ArmIkSideConfig(
            body_name=profile.ik_body_names["left"],
            body_offset_pos=profile.ik_body_offset_pos["left"],
            body_offset_quat_xyzw=profile.ik_body_offset_quat_xyzw["left"],
            target_orientation_correction_quat_xyzw=(
                profile.ik_target_orientation_correction_quat_xyzw["left"]
            ),
            joint_names=ARM_JOINTS["left"],
        ),
        "right": ArmIkSideConfig(
            body_name=profile.ik_body_names["right"],
            body_offset_pos=profile.ik_body_offset_pos["right"],
            body_offset_quat_xyzw=profile.ik_body_offset_quat_xyzw["right"],
            target_orientation_correction_quat_xyzw=(
                profile.ik_target_orientation_correction_quat_xyzw["right"]
            ),
            joint_names=ARM_JOINTS["right"],
        ),
    }

    return ArmIkRuntimeConfig(
        status_label=profile.status_label,
        enabled=True,
        pose_scale=1.0,
        pose_z_offset=0.0,
        command_type="pose",
        startup_relative_position=True,
        startup_relative_orientation=True,
        position_error_scale=0.8,
        orientation_error_scale=0.8,
        position_deadband_m=0.004,
        orientation_deadband_rad=0.08,
        ik_method="dls",
        damping=0.05,
        smoothing_alpha=0.80,
        clamp_to_joint_limits=True,
        sides=sides,
    )


def _load_isaac_lab():
    from isaaclab.app import AppLauncher

    return AppLauncher


class DualArmIkController:
    """Drive G1 arm joints from left/right end-effector pose targets."""

    def __init__(
        self,
        robot: Any,
        config: ArmIkRuntimeConfig,
        *,
        device: str,
        pose_binding: AvpRobotFrameBinding | None,
    ) -> None:
        import torch
        from isaaclab.controllers import DifferentialIKController
        from isaaclab.controllers.differential_ik_cfg import DifferentialIKControllerCfg
        from isaaclab.utils import math as math_utils

        self._robot = robot
        self._config = config
        self._pose_binding = pose_binding
        self._device = device
        self._torch = torch
        self._math_utils = math_utils
        self._controllers: dict[str, Any] = {}
        self._joint_ids: dict[str, Sequence[int] | slice] = {}
        self._joint_id_lists: dict[str, list[int]] = {}
        self._joint_names: dict[str, tuple[str, ...]] = {}
        self._body_ids: dict[str, int] = {}
        self._body_names: dict[str, str] = {}
        self._jacobi_body_ids: dict[str, int] = {}
        self._jacobi_joint_ids: dict[str, list[int]] = {}
        self._offset_pos: dict[str, Any] = {}
        self._offset_rot: dict[str, Any] = {}
        self._target_rot_correction: dict[str, Any] = {}
        self._last_targets: dict[str, Any] = {}
        self._startup_target_refs: dict[str, tuple[Any, Any, Any, Any]] = {}
        self._startup_ref_announced: set[str] = set()

        ik_params = self._ik_params()
        for side, side_config in config.sides.items():
            joint_ids, resolved_joint_names = robot.find_joints(
                list(side_config.joint_names), preserve_order=True
            )
            missing = [
                name
                for name in side_config.joint_names
                if name not in resolved_joint_names
            ]
            if missing:
                raise RuntimeError(
                    f"{self._config.status_label} USD is missing {side} arm joints: {missing[:8]}"
                )

            body_ids, body_names = robot.find_bodies(side_config.body_name)
            if len(body_ids) != 1:
                raise RuntimeError(
                    f"Expected one {side} IK body match for {side_config.body_name!r}; "
                    f"got {len(body_ids)}: {body_names}"
                )

            body_idx = int(body_ids[0])
            joint_id_list = [int(joint_id) for joint_id in joint_ids]
            if robot.is_fixed_base:
                jacobi_body_idx = body_idx - 1
                jacobi_joint_ids = joint_id_list
            else:
                jacobi_body_idx = body_idx
                jacobi_joint_ids = [joint_id + 6 for joint_id in joint_id_list]

            controller_cfg = DifferentialIKControllerCfg(
                command_type=config.command_type,
                use_relative_mode=False,
                ik_method=config.ik_method,
                ik_params=ik_params,
            )
            self._controllers[side] = DifferentialIKController(
                cfg=controller_cfg,
                num_envs=1,
                device=device,
            )
            self._joint_id_lists[side] = joint_id_list
            self._joint_ids[side] = (
                slice(None) if len(joint_id_list) == robot.num_joints else joint_id_list
            )
            self._joint_names[side] = tuple(str(name) for name in resolved_joint_names)
            self._body_ids[side] = body_idx
            self._body_names[side] = str(body_names[0])
            self._jacobi_body_ids[side] = int(jacobi_body_idx)
            self._jacobi_joint_ids[side] = jacobi_joint_ids
            self._offset_pos[side] = torch.tensor(
                side_config.body_offset_pos,
                dtype=torch.float32,
                device=device,
            ).unsqueeze(0)
            self._offset_rot[side] = torch.tensor(
                side_config.body_offset_quat_xyzw,
                dtype=torch.float32,
                device=device,
            ).unsqueeze(0)
            self._target_rot_correction[side] = self._math_utils.quat_unique(
                self._math_utils.normalize(
                    torch.tensor(
                        side_config.target_orientation_correction_quat_xyzw,
                        dtype=torch.float32,
                        device=device,
                    ).unsqueeze(0)
                )
            )

    def _ik_params(self) -> dict[str, float]:
        if self._config.ik_method == "dls":
            return {"lambda_val": self._config.damping}
        if self._config.ik_method == "pinv":
            return {"k_val": 1.0}
        if self._config.ik_method == "trans":
            return {"k_val": 1.0}
        if self._config.ik_method == "svd":
            return {"k_val": 1.0, "min_singular_value": 1.0e-5}
        return {}

    def _frame_pose_root(self, side: str) -> tuple[Any, Any]:
        body_idx = self._body_ids[side]
        ee_pos_w = as_torch(self._robot.data.body_pos_w)[:, body_idx]
        ee_quat_w = as_torch(self._robot.data.body_quat_w)[:, body_idx]
        root_pos_w = as_torch(self._robot.data.root_pos_w)
        root_quat_w = as_torch(self._robot.data.root_quat_w)
        ee_pos_b, ee_quat_b = self._math_utils.subtract_frame_transforms(
            root_pos_w, root_quat_w, ee_pos_w, ee_quat_w
        )
        return self._math_utils.combine_frame_transforms(
            ee_pos_b,
            ee_quat_b,
            self._offset_pos[side],
            self._offset_rot[side],
        )

    def _target_pose_root(
        self, side: str, pose: Mapping[str, Any]
    ) -> tuple[Any, Any] | None:
        if self._pose_binding is not None:
            target_pose = self._pose_binding.transform_pose(side, pose)
            if target_pose is None:
                return None
            pos_w_np, quat_w_np = target_pose
        else:
            pos_w_np, quat_w_np = openxr_pose_to_isaac_pose(
                pose,
                scale=self._config.pose_scale,
                offset_z=self._config.pose_z_offset,
            )
        return self._target_pose_root_from_world_pose(
            pos_w_np,
            quat_w_np,
            side=side,
            apply_target_rot_correction=True,
        )

    def _target_pose_root_from_world_pose(
        self,
        pos_w_np: Sequence[float] | np.ndarray,
        quat_w_np: Sequence[float] | np.ndarray,
        *,
        side: str | None = None,
        apply_target_rot_correction: bool = False,
    ) -> tuple[Any, Any]:
        pos_w = self._torch.as_tensor(
            pos_w_np,
            dtype=self._torch.float32,
            device=self._device,
        ).unsqueeze(0)
        quat_w = self._torch.as_tensor(
            normalize_quat_xyzw(quat_w_np),
            dtype=self._torch.float32,
            device=self._device,
        ).unsqueeze(0)
        if apply_target_rot_correction:
            if side is None:
                raise ValueError(
                    "side is required when applying target orientation correction"
                )
            quat_w = self._math_utils.normalize(
                self._math_utils.quat_mul(quat_w, self._target_rot_correction[side])
            )
        else:
            quat_w = self._math_utils.normalize(quat_w)
        quat_w = self._math_utils.quat_unique(quat_w)
        root_pos_w = as_torch(self._robot.data.root_pos_w)
        root_quat_w = as_torch(self._robot.data.root_quat_w)
        return self._math_utils.subtract_frame_transforms(
            root_pos_w, root_quat_w, pos_w, quat_w
        )

    def _startup_relative_target(
        self,
        side: str,
        target_pos: Any,
        target_quat: Any,
        ee_pos_curr: Any,
        ee_quat_curr: Any,
    ) -> tuple[Any, Any]:
        if not (
            self._config.startup_relative_position
            or self._config.startup_relative_orientation
        ):
            return target_pos, target_quat

        ref = self._startup_target_refs.get(side)
        if ref is None:
            ref = (
                target_pos.detach().clone(),
                self._math_utils.quat_unique(
                    self._math_utils.normalize(target_quat.detach().clone())
                ),
                ee_pos_curr.detach().clone(),
                self._math_utils.quat_unique(
                    self._math_utils.normalize(ee_quat_curr.detach().clone())
                ),
            )
            self._startup_target_refs[side] = ref
            self._announce_startup_relative_target(side, ref)

        target_start_pos, target_start_quat, ee_start_pos, ee_start_quat = ref
        adjusted_pos = target_pos
        adjusted_quat = target_quat

        # AVP optical wrists and the robot EE rarely share a reliable absolute
        # pose. Bind the first valid target to the current simulated EE, then
        # command startup-relative translation and rotation deltas.
        if self._config.startup_relative_position:
            adjusted_pos = ee_start_pos + (target_pos - target_start_pos)
        if self._config.startup_relative_orientation:
            target_quat = self._math_utils.quat_unique(
                self._math_utils.normalize(target_quat)
            )
            quat_delta = self._math_utils.quat_mul(
                target_quat,
                self._math_utils.quat_inv(target_start_quat),
            )
            adjusted_quat = self._math_utils.normalize(
                self._math_utils.quat_mul(quat_delta, ee_start_quat)
            )
            adjusted_quat = self._math_utils.quat_unique(adjusted_quat)
        return adjusted_pos, adjusted_quat

    def _announce_startup_relative_target(
        self,
        side: str,
        ref: tuple[Any, Any, Any, Any],
    ) -> None:
        if side in self._startup_ref_announced:
            return
        target_start_pos, target_start_quat, ee_start_pos, ee_start_quat = ref
        print(
            f"[{self._config.status_label}] {side} IK startup target reference calibrated "
            f"relative_position={self._config.startup_relative_position} "
            f"relative_orientation={self._config.startup_relative_orientation} "
            f"target_pos={np.round(target_start_pos[0].detach().cpu().numpy(), 4).tolist()} "
            f"ee_pos={np.round(ee_start_pos[0].detach().cpu().numpy(), 4).tolist()} "
            f"target_quat_xyzw={np.round(target_start_quat[0].detach().cpu().numpy(), 4).tolist()} "
            f"ee_quat_xyzw={np.round(ee_start_quat[0].detach().cpu().numpy(), 4).tolist()}",
            flush=True,
        )
        self._startup_ref_announced.add(side)

    def _compute_delta_joint_pos(self, delta_pose: Any, jacobian: Any) -> Any:
        if self._config.ik_method == "pinv":
            jacobian_pinv = self._torch.linalg.pinv(jacobian)
            return (jacobian_pinv @ delta_pose.unsqueeze(-1)).squeeze(-1)
        if self._config.ik_method == "svd":
            min_singular_value = 1.0e-5
            U, S, Vh = self._torch.linalg.svd(jacobian)
            S_inv = 1.0 / S
            S_inv = self._torch.where(
                min_singular_value < S,
                S_inv,
                self._torch.zeros_like(S_inv),
            )
            jacobian_pinv = (
                self._torch.transpose(Vh, dim0=1, dim1=2)[:, :, : jacobian.shape[1]]
                @ self._torch.diag_embed(S_inv)
                @ self._torch.transpose(U, dim0=1, dim1=2)
            )
            return (jacobian_pinv @ delta_pose.unsqueeze(-1)).squeeze(-1)
        if self._config.ik_method == "trans":
            jacobian_t = self._torch.transpose(jacobian, dim0=1, dim1=2)
            return (jacobian_t @ delta_pose.unsqueeze(-1)).squeeze(-1)
        if self._config.ik_method == "dls":
            jacobian_t = self._torch.transpose(jacobian, dim0=1, dim1=2)
            lambda_val = self._config.damping
            lambda_matrix = (lambda_val**2) * self._torch.eye(
                n=jacobian.shape[1],
                device=self._device,
            )
            return (
                jacobian_t
                @ self._torch.inverse(jacobian @ jacobian_t + lambda_matrix)
                @ delta_pose.unsqueeze(-1)
            ).squeeze(-1)
        raise ValueError(
            f"Unsupported inverse-kinematics method: {self._config.ik_method}"
        )

    def _compute_joint_targets(
        self,
        side: str,
        ee_pos_curr: Any,
        ee_quat_curr: Any,
        joint_pos: Any,
    ) -> Any:
        jacobian = self._frame_jacobian(side)
        controller = self._controllers[side]
        if self._config.command_type == "position":
            return controller.compute(
                ee_pos_curr,
                ee_quat_curr,
                jacobian,
                joint_pos,
            )

        position_error, axis_angle_error = self._math_utils.compute_pose_error(
            ee_pos_curr,
            ee_quat_curr,
            controller.ee_pos_des,
            controller.ee_quat_des,
            rot_error_type="axis_angle",
        )
        if self._config.position_deadband_m > 0.0:
            position_norm = self._torch.linalg.norm(position_error, dim=1, keepdim=True)
            position_error = self._torch.where(
                position_norm <= self._config.position_deadband_m,
                self._torch.zeros_like(position_error),
                position_error,
            )
        if self._config.orientation_deadband_rad > 0.0:
            orientation_norm = self._torch.linalg.norm(
                axis_angle_error, dim=1, keepdim=True
            )
            axis_angle_error = self._torch.where(
                orientation_norm <= self._config.orientation_deadband_rad,
                self._torch.zeros_like(axis_angle_error),
                axis_angle_error,
            )
        # Pose-mode wrist targets are much noisier in orientation than in translation.
        # Down-weight angular error so small AVP wrist rotations do not yank the whole
        # arm into a large reconfiguration before the translational target is reached.
        position_error = position_error * self._config.position_error_scale
        axis_angle_error = axis_angle_error * self._config.orientation_error_scale
        pose_error = self._torch.cat((position_error, axis_angle_error), dim=1)
        if bool(self._torch.all(self._torch.abs(pose_error) <= 1.0e-9)):
            return joint_pos
        delta_joint_pos = self._compute_delta_joint_pos(pose_error, jacobian)
        return joint_pos + delta_joint_pos

    def _frame_jacobian(self, side: str):
        jacobian = as_torch(self._robot.root_physx_view.get_jacobians())[
            :, self._jacobi_body_ids[side], :, self._jacobi_joint_ids[side]
        ].clone()
        root_quat_w = as_torch(self._robot.data.root_quat_w)
        root_rot_b_w = self._math_utils.matrix_from_quat(
            self._math_utils.quat_inv(root_quat_w)
        )
        jacobian[:, 0:3, :] = self._torch.bmm(root_rot_b_w, jacobian[:, 0:3, :])
        jacobian[:, 3:, :] = self._torch.bmm(root_rot_b_w, jacobian[:, 3:, :])
        offset_pos = self._offset_pos[side]
        offset_rot = self._offset_rot[side]
        jacobian[:, 0:3, :] += self._torch.bmm(
            -self._math_utils.skew_symmetric_matrix(offset_pos),
            jacobian[:, 3:, :],
        )
        jacobian[:, 3:, :] = self._torch.bmm(
            self._math_utils.matrix_from_quat(offset_rot),
            jacobian[:, 3:, :],
        )
        return jacobian

    def _apply_target_pose_root(
        self,
        side: str,
        target_pose_root: tuple[Any, Any],
    ) -> None:
        ee_pos_curr, ee_quat_curr = self._frame_pose_root(side)
        target_pos, target_quat = target_pose_root
        target_pos, target_quat = self._startup_relative_target(
            side,
            target_pos,
            target_quat,
            ee_pos_curr,
            ee_quat_curr,
        )
        command = (
            target_pos
            if self._config.command_type == "position"
            else self._torch.cat((target_pos, target_quat), dim=1)
        )
        self._controllers[side].set_command(command, ee_pos_curr, ee_quat_curr)
        joint_pos = as_torch(self._robot.data.joint_pos)[:, self._joint_ids[side]]
        joint_targets = self._compute_joint_targets(
            side,
            ee_pos_curr,
            ee_quat_curr,
            joint_pos,
        )

        if self._config.clamp_to_joint_limits:
            limits = as_torch(self._robot.data.soft_joint_pos_limits)[
                :, self._joint_ids[side], :
            ]
            joint_targets = self._torch.clamp(
                joint_targets, limits[:, :, 0], limits[:, :, 1]
            )

        previous = self._last_targets.get(side)
        if previous is not None and self._config.smoothing_alpha < 1.0:
            alpha = self._config.smoothing_alpha
            joint_targets = previous * (1.0 - alpha) + joint_targets * alpha

        self._last_targets[side] = joint_targets
        self._robot.set_joint_position_target(
            target=joint_targets,
            joint_ids=self._joint_ids[side],
        )

    def update(self, sample: Mapping[str, Any]) -> None:
        if not self._config.enabled:
            return

        for side in ("left", "right"):
            pose = sample["ee_poses"].get(side)
            if pose is None:
                target = self._last_targets.get(side)
                if target is not None:
                    self._robot.set_joint_position_target(
                        target=target,
                        joint_ids=self._joint_ids[side],
                    )
                continue

            target_pose = self._target_pose_root(side, pose)
            if target_pose is None:
                continue
            self._apply_target_pose_root(side, target_pose)

    def reset_startup_references(self) -> None:
        self._startup_target_refs.clear()
        self._startup_ref_announced.clear()
        print(
            f"[{self._config.status_label}] arm IK startup target references cleared; "
            "waiting for re-arm calibration.",
            flush=True,
        )


def _find_required_joint_ids(
    robot: Any,
    joint_names: Sequence[str],
    side: str,
    *,
    status_label: str,
) -> list[int]:
    joint_ids, resolved_names = robot.find_joints(
        list(joint_names), preserve_order=True
    )
    missing = [name for name in joint_names if name not in resolved_names]
    if missing:
        available = list(getattr(robot.data, "joint_names", []) or [])
        raise RuntimeError(
            f"{status_label} USD is missing {side} hand joints. "
            f"Missing first entries: {missing[:8]}; available count={len(available)}"
        )
    return list(joint_ids)


def _default_joint_positions(
    robot: Any,
    joint_ids: Sequence[int],
) -> np.ndarray:
    default_joint_pos = as_torch(robot.data.default_joint_pos)
    values = default_joint_pos[0, list(joint_ids)].detach().cpu().numpy()
    return values.astype(np.float32)


def _soft_joint_limits(robot: Any, joint_ids: Sequence[int]) -> np.ndarray | None:
    limits = as_torch(robot.data.soft_joint_pos_limits)
    values = limits[0, list(joint_ids), :].detach().cpu().numpy()
    if values.shape != (len(joint_ids), 2):
        return None
    return values.astype(np.float32)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    AppLauncher = _load_isaac_lab()
    parser = argparse.ArgumentParser(
        description="Run a minimal G1 Isaac Lab scene driven by AVP + MANUS teleop."
    )
    parser.add_argument("--config", default=str(_default_config_path()))
    parser.add_argument("--robot-usd", default=None)
    parser.add_argument("--robot-prim", default=None)
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument(
        "--robot-height",
        type=float,
        default=None,
        help="Optional override for robot.initial_world_position z.",
    )
    parser.add_argument("--light-intensity", type=float, default=3000.0)
    parser.add_argument(
        "--scene-only",
        action="store_true",
        help="Load the minimal scene and robot without starting OpenXR/MANUS teleop.",
    )
    AppLauncher.add_app_launcher_args(parser)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config_path = Path(args.config).expanduser().resolve()
    teleop_config = load_yaml_file(config_path)
    teleop_config["_config_dir"] = str(config_path.parent)
    robot_profile = robot_profile_from_config(teleop_config)
    status_label = robot_profile.status_label
    head_view_camera_config = _head_view_camera_config(teleop_config)
    third_viewpoint_config = _third_viewpoint_config(teleop_config)
    initial_world_position = _robot_initial_world_position(teleop_config)
    initial_world_orientation_xyzw = _robot_initial_world_orientation_xyzw(
        teleop_config
    )
    wuji_hand_config = wuji_hand_runtime_config(teleop_config)
    arm_ik_config = _arm_ik_runtime_config(teleop_config)
    avp_frame_binding_config = avp_frame_binding_runtime_config(teleop_config)
    if args.robot_height is not None:
        initial_world_position = (
            initial_world_position[0],
            initial_world_position[1],
            float(args.robot_height),
        )
    robot_usd = (
        Path(args.robot_usd).expanduser().resolve()
        if args.robot_usd
        else example_path(robot_profile.default_usd_relpath)
    )
    if not robot_usd.is_file():
        raise FileNotFoundError(f"{status_label} USD not found: {robot_usd}")
    robot_prim = str(args.robot_prim or robot_profile.robot_prim)

    AppLauncher = _load_isaac_lab()
    app_launcher = AppLauncher(args)
    simulation_app = app_launcher.app

    import carb.input
    import omni.appwindow
    import omni.kit.viewport.utility
    import omni.ui
    import omni.usd
    import torch
    from isaacsim.core.rendering_manager import ViewportManager
    from pxr import Gf, UsdGeom

    import isaaclab.sim as sim_utils
    from isaaclab.sim import SimulationContext

    sim_cfg = sim_utils.SimulationCfg(dt=1.0 / 60.0, device=args.device)
    sim = SimulationContext(sim_cfg)
    sim.set_camera_view([3.0, -4.0, 2.0], [0.0, 0.0, 0.9])
    render_enabled = not args.headless

    scene_config = G1WujiSceneConfig(
        robot_prim=robot_prim,
        robot_usd=robot_usd,
        initial_world_position=initial_world_position,
        initial_world_orientation_xyzw=initial_world_orientation_xyzw,
        initial_hand_joint_positions=wuji_hand_config.initial_joint_positions,
        light_intensity=args.light_intensity,
    )
    robot = design_g1_wuji_scene(scene_config)

    sim.reset()
    sim_dt = sim.get_physics_dt()
    left_joint_ids = _find_required_joint_ids(
        robot,
        wuji_hand_config.left_joint_names,
        "left",
        status_label=status_label,
    )
    right_joint_ids = _find_required_joint_ids(
        robot,
        wuji_hand_config.right_joint_names,
        "right",
        status_label=status_label,
    )
    left_initial_targets = _default_joint_positions(
        robot,
        left_joint_ids,
    )
    right_initial_targets = _default_joint_positions(
        robot,
        right_joint_ids,
    )
    left_postprocessor = HandTargetPostProcessor(
        joint_names=wuji_hand_config.left_joint_names,
        initial_targets=left_initial_targets,
        joint_limits=_soft_joint_limits(robot, left_joint_ids),
        config=wuji_hand_config,
        side="left",
    )
    right_postprocessor = HandTargetPostProcessor(
        joint_names=wuji_hand_config.right_joint_names,
        initial_targets=right_initial_targets,
        joint_limits=_soft_joint_limits(robot, right_joint_ids),
        config=wuji_hand_config,
        side="right",
    )
    wuji_backend = WujiHandTargetBackend(wuji_hand_config)
    avp_frame_binding = (
        AvpRobotFrameBinding(
            robot,
            arm_ik_config,
            avp_frame_binding_config,
            pose_scale=arm_ik_config.pose_scale,
            pose_z_offset=arm_ik_config.pose_z_offset,
        )
        if avp_frame_binding_config.enabled
        else None
    )
    arm_ik = (
        DualArmIkController(
            robot,
            arm_ik_config,
            device=sim.device,
            pose_binding=avp_frame_binding,
        )
        if arm_ik_config.enabled
        else None
    )
    stage = omni.usd.get_context().get_stage()
    head_link_prim = None
    if head_view_camera_config.enabled:
        head_link_prim = stage.GetPrimAtPath(
            head_view_camera_config.head_link_prim_path
        )
        if head_link_prim is None or not head_link_prim.IsValid():
            raise FileNotFoundError(
                f"{status_label} head camera prim does not exist: "
                f"{head_view_camera_config.head_link_prim_path}"
            )
        print(
            f"[{status_label}] head camera uses prim {head_link_prim.GetPath()}",
            flush=True,
        )
    xform_cache = UsdGeom.XformCache()
    viewport_api = omni.kit.viewport.utility.get_active_viewport()
    default_viewport_camera_path = (
        str(viewport_api.camera_path)
        if viewport_api is not None and viewport_api.camera_path is not None
        else None
    )
    head_view_camera = (
        HeadViewCameraController(
            stage=stage,
            UsdGeom=UsdGeom,
            Gf=Gf,
            viewport_api=viewport_api,
            config=head_view_camera_config,
            head_link_prim=head_link_prim,
            avp_frame_binding=avp_frame_binding,
        )
        if head_view_camera_config.enabled and stage is not None
        else None
    )
    third_viewpoint_reference_prim = None
    if third_viewpoint_config is not None and stage is not None:
        third_viewpoint_reference_path = (
            f"{robot_prim.rstrip('/')}/{avp_frame_binding_config.robot_reference_body}"
        )
        third_viewpoint_reference_prim = stage.GetPrimAtPath(
            third_viewpoint_reference_path
        )
        if (
            third_viewpoint_reference_prim is None
            or not third_viewpoint_reference_prim.IsValid()
        ):
            raise FileNotFoundError(
                f"{status_label} third viewpoint reference prim does not exist: "
                f"{third_viewpoint_reference_path}"
            )
    third_viewpoint = (
        ThirdViewpointController(
            Gf=Gf,
            ViewportManager=ViewportManager,
            viewport_utility=omni.kit.viewport.utility,
            ui=omni.ui,
            config=third_viewpoint_config,
            reference_prim=third_viewpoint_reference_prim,
            main_viewport_api=viewport_api,
            main_camera_path=(
                None if head_view_camera is None else head_view_camera.camera_path
            ),
            status_label=status_label,
        )
        if (
            third_viewpoint_config is not None
            and stage is not None
            and not args.headless
        )
        else None
    )
    if third_viewpoint is None:
        _hide_third_viewpoint_window(omni.kit.viewport.utility)
    teleop: TeleopMain | None = None
    teleop_started = False
    scene_warmed_up = False
    robot_default_joint_pos = as_torch(robot.data.default_joint_pos).clone()
    robot_default_joint_vel = as_torch(robot.data.default_joint_vel).clone()
    robot.set_joint_position_target(
        target=torch.as_tensor(left_initial_targets, device=sim.device).unsqueeze(0),
        joint_ids=left_joint_ids,
    )
    robot.set_joint_position_target(
        target=torch.as_tensor(right_initial_targets, device=sim.device).unsqueeze(0),
        joint_ids=right_joint_ids,
    )

    print(
        f"{status_label} teleop scene ready: "
        f"{len(left_joint_ids)} left hand joints, {len(right_joint_ids)} right hand joints, "
        f"hand_retarget={wuji_hand_config.retarget_backend}, "
        f"arm_ik={arm_ik_config.enabled}, "
        f"avp_frame_binding={avp_frame_binding_config.enabled}, "
        f"head_view_camera={head_view_camera is not None}, "
        f"third_viewpoint={third_viewpoint is not None}."
    )

    def step_scene_once() -> None:
        robot.write_data_to_sim()
        sim.step(render=render_enabled)
        robot.update(sim_dt)
        if head_view_camera is not None:
            head_view_camera.update(xform_cache=xform_cache)

    if args.scene_only:
        print("Scene-only mode: OpenXR/MANUS teleop is not started.")
        start_time = time.monotonic()
        while simulation_app.is_running():
            if (
                args.duration_s > 0.0
                and time.monotonic() - start_time >= args.duration_s
            ):
                break
            step_scene_once()
        simulation_app.close()
        return 0

    teleop_armed = False
    start_waiting_announced = False
    keyboard_start_requested = False
    keyboard_reset_requested = False

    app_window = omni.appwindow.get_default_app_window()
    input_interface = carb.input.acquire_input_interface()

    def on_keyboard_event(event, *args, **kwargs):
        nonlocal keyboard_reset_requested, keyboard_start_requested
        if event.type == carb.input.KeyboardEventType.KEY_PRESS:
            if event.input == carb.input.KeyboardInput.B:
                keyboard_start_requested = True
            elif event.input == carb.input.KeyboardInput.R:
                keyboard_reset_requested = True
        return True

    keyboard_subscription = (
        input_interface.subscribe_to_keyboard_events(
            app_window.get_keyboard(),
            on_keyboard_event,
        )
        if app_window is not None and app_window.get_keyboard() is not None
        else None
    )

    def hold_robot_targets() -> None:
        robot.set_joint_position_target(
            target=torch.as_tensor(left_initial_targets, device=sim.device).unsqueeze(
                0
            ),
            joint_ids=left_joint_ids,
        )
        robot.set_joint_position_target(
            target=torch.as_tensor(right_initial_targets, device=sim.device).unsqueeze(
                0
            ),
            joint_ids=right_joint_ids,
        )

    def restore_robot_initial_pose() -> None:
        robot.write_joint_state_to_sim(
            robot_default_joint_pos,
            robot_default_joint_vel,
        )
        robot.set_joint_position_target(
            target=robot_default_joint_pos,
        )
        if arm_ik is not None:
            arm_ik._last_targets.clear()

    def reset_teleop_calibration() -> None:
        if avp_frame_binding is not None:
            avp_frame_binding.reset_calibration()
        if arm_ik is not None:
            arm_ik.reset_startup_references()
        if head_view_camera is not None:
            head_view_camera.deactivate()
            if viewport_api is not None and default_viewport_camera_path:
                viewport_api.camera_path = default_viewport_camera_path
        if third_viewpoint is not None:
            third_viewpoint.deactivate()

    def close_openxr_runtime() -> None:
        nonlocal teleop, teleop_started
        if teleop_started and teleop is not None:
            teleop.__exit__(None, None, None)
        teleop = None
        teleop_started = False

    def start_openxr_runtime() -> None:
        nonlocal teleop, teleop_started
        teleop = TeleopMain(teleop_config, config_dir=config_path.parent)
        teleop.__enter__()
        teleop_started = True
        print(
            f"[{status_label}] OpenXR teleop session started.",
            flush=True,
        )

    start_time = time.monotonic()
    if not simulation_app.is_running():
        has_keyboard = bool(
            app_window is not None and app_window.get_keyboard() is not None
        )
        print(
            f"[{status_label}] simulation app is not running at teleop loop start; "
            "exiting before the first teleop frame. "
            f"headless={args.headless} "
            f"app_window={app_window is not None} "
            f"keyboard={has_keyboard}",
            flush=True,
        )
    while simulation_app.is_running():
        if args.duration_s > 0.0 and time.monotonic() - start_time >= args.duration_s:
            break

        start_button_rising = keyboard_start_requested
        keyboard_start_requested = False
        reset_button_rising = keyboard_reset_requested
        keyboard_reset_requested = False

        if reset_button_rising:
            teleop_armed = False
            start_waiting_announced = False
            restore_robot_initial_pose()
            reset_teleop_calibration()
            print(
                f"[{status_label}] teleop reset; robot returned to its initial joint pose. "
                "Press keyboard B to recalibrate and start again.",
                flush=True,
            )

        if not scene_warmed_up:
            hold_robot_targets()
            step_scene_once()
            scene_warmed_up = True
            continue

        if teleop is None:
            start_openxr_runtime()

        sample = teleop.step()
        if not teleop_armed:
            if not start_waiting_announced:
                print(
                    f"[{status_label}] teleop is disarmed; press keyboard B to recalibrate "
                    "and start teleop. Press keyboard R to force reset back to this state.",
                    flush=True,
                )
                start_waiting_announced = True
            if start_button_rising:
                teleop_armed = True
                start_waiting_announced = False
                reset_teleop_calibration()
                print(
                    f"[{status_label}] teleop armed at frame={int(sample.get('frame_count', 0))}; "
                    "starting fresh AVP head-hand calibration "
                    f"(averaging {avp_frame_binding_config.calibration_window_s:.1f}s).",
                    flush=True,
                )
            else:
                hold_robot_targets()
                step_scene_once()
                continue

        raw_left_targets, raw_right_targets = wuji_backend.targets(sample)

        left_targets = left_postprocessor.process(raw_left_targets)
        right_targets = right_postprocessor.process(raw_right_targets)

        if left_targets is not None:
            robot.set_joint_position_target(
                target=torch.as_tensor(left_targets, device=sim.device).unsqueeze(0),
                joint_ids=left_joint_ids,
            )
        if right_targets is not None:
            robot.set_joint_position_target(
                target=torch.as_tensor(right_targets, device=sim.device).unsqueeze(0),
                joint_ids=right_joint_ids,
            )
        if avp_frame_binding is not None:
            avp_frame_binding.update_calibration(sample)
            avp_frame_binding.update_runtime_state(sample)
            if (
                head_view_camera is not None
                and head_view_camera_config.activate_on_calibration
                and avp_frame_binding.calibrated
            ):
                if third_viewpoint is not None:
                    third_viewpoint.activate(xform_cache=xform_cache)
                head_view_camera.activate()
        if arm_ik is not None:
            arm_ik.update(sample)

        step_scene_once()

    if keyboard_subscription is not None:
        input_interface.unsubscribe_from_keyboard_events(
            app_window.get_keyboard(),
            keyboard_subscription,
        )
    close_openxr_runtime()
    simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
