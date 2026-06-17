# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Minimal Isaac Lab scene for AVP + MANUS teleop on G1-Wuji.

Run this script with an Isaac Sim / Isaac Lab Python environment. It intentionally
keeps the simulation side small: a ground plane, a light, the selected G1 USD,
wrist target markers, and live hand joint targets from ``TeleopMain``.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
import threading
import time
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

import numpy as np

from .devices.avp_manus_stream import TeleopMain
from .paths import default_config_path, ensure_import_paths, resolve_repo_relative_path
from .robots.g1_wuji.debug_viz import (
    DebugVizSceneConfig,
    create_debug_viz,
    debug_viz_runtime_config,
    find_head_like_prim,
    sample_target_poses,
    update_frame_axis_markers,
    update_head_marker,
    update_wrist_markers,
    walk_child_prims,
)
from .robots.g1_wuji.runtime import (
    AvpFrameBindingRuntimeConfig,
    AvpRobotFrameBinding,
    HandTargetPostProcessor,
    WujiHandRuntimeConfig,
    WujiHandTargetBackend,
    avp_frame_binding_runtime_config,
    matrix_to_quat_xyzw,
    normalize_quat_xyzw,
    openxr_pose_to_isaac_pose,
    ordered_hand_targets,
    robot_profile_from_config,
    resolve_marker_pose as resolve_avp_marker_pose,
    wuji_hand_runtime_config,
)
from .robots.g1_wuji.scene import (
    G1WujiSceneConfig,
    design_g1_wuji_scene,
)


os.environ.setdefault("WARP_CACHE_PATH", "/tmp/isaacteleop-warp-cache")


def _enable_kit_extension(extension_name: str) -> None:
    """Best-effort enable of a packaged Kit extension by name."""

    try:
        import omni.kit.app

        ext_manager = omni.kit.app.get_app().get_extension_manager()
        if ext_manager is not None and not ext_manager.is_extension_enabled(
            extension_name
        ):
            ext_manager.set_extension_enabled_immediate(extension_name, True)
    except Exception:
        pass


def _inject_isaacsim_extension_root(extension_name: str) -> None:
    """Append a packaged Isaac Sim extension root from ``extscache`` or ``exts`` to ``sys.path``."""

    for path_entry in sys.path:
        if "site-packages" not in path_entry:
            continue
        isaacsim_root = Path(path_entry) / "isaacsim"
        extscache_dir = isaacsim_root / "extscache"
        if extscache_dir.is_dir():
            matches = sorted(extscache_dir.glob(f"{extension_name}-*"))
            if matches:
                ext_path = str(matches[-1])
                if ext_path not in sys.path:
                    sys.path.append(ext_path)
                return

        exts_dir = isaacsim_root / "exts" / extension_name
        if exts_dir.is_dir():
            ext_path = str(exts_dir)
            if ext_path not in sys.path:
                sys.path.append(ext_path)
            return


def _ensure_carb_input_available() -> None:
    """Load ``carb.input`` explicitly so keyboard events work across Kit variants."""

    try:
        import carb

        if hasattr(carb, "input"):
            return
        import carb.input  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Failed to load carb.input required for teleop keyboard shortcuts."
        ) from exc


def _import_omni_appwindow():
    """Import ``omni.appwindow`` even when Kit hasn't pre-enabled the extension."""

    _enable_kit_extension("omni.appwindow")

    try:
        import omni.appwindow as omni_appwindow

        return omni_appwindow
    except Exception:
        _inject_isaacsim_extension_root("omni.appwindow")
        _enable_kit_extension("omni.appwindow")
        try:
            import omni.appwindow as omni_appwindow

            return omni_appwindow
        except Exception as exc:
            raise RuntimeError(
                "Failed to load omni.appwindow required for teleop keyboard shortcuts."
            ) from exc


def _import_omni_viewport_utility():
    """Import ``omni.kit.viewport.utility`` when Isaac Sim hasn't enabled it yet."""

    _enable_kit_extension("omni.kit.viewport.window")
    _enable_kit_extension("omni.kit.viewport.utility")

    try:
        return importlib.import_module("omni.kit.viewport.utility")
    except Exception:
        _inject_isaacsim_extension_root("omni.kit.viewport.utility")
        _enable_kit_extension("omni.kit.viewport.window")
        _enable_kit_extension("omni.kit.viewport.utility")
        try:
            return importlib.import_module("omni.kit.viewport.utility")
        except Exception as exc:
            raise RuntimeError(
                "Failed to load omni.kit.viewport.utility required for head-view camera control."
            ) from exc


def _import_omni_replicator_core():
    """Import ``omni.replicator.core`` when Isaac Sim hasn't enabled it yet."""

    _enable_kit_extension("omni.replicator.core")

    try:
        return importlib.import_module("omni.replicator.core")
    except Exception:
        _inject_isaacsim_extension_root("omni.replicator.core")
        _enable_kit_extension("omni.replicator.core")
        try:
            return importlib.import_module("omni.replicator.core")
        except Exception as exc:
            raise ModuleNotFoundError(
                "robot.head_view_xr_display requires omni.replicator.core."
            ) from exc


def _head_view_xr_display_preflight_error(camera_prim_path: str | None) -> str | None:
    """Return a short reason when direct camera render-product prerequisites are not ready."""

    if not camera_prim_path:
        return "no head-view camera prim is available"
    try:
        _import_omni_replicator_core()
    except Exception as exc:
        return f"failed to import omni.replicator.core ({type(exc).__name__}: {exc})"
    return None


def _disable_robot_transmissive_materials(
    *, stage: Any, robot_root_prim: Any, status_label: str
) -> None:
    """Make the robot body render opaque even when the source USD uses a transmissive OmniSurface."""

    if stage is None or robot_root_prim is None or not robot_root_prim.IsValid():
        return

    root_prefix = f"{robot_root_prim.GetPath()}/"
    patched_shader_paths: list[str] = []
    for prim in stage.Traverse():
        prim_path = str(prim.GetPath())
        if not prim_path.startswith(root_prefix):
            continue
        if prim.GetTypeName() != "Shader" or not prim_path.endswith(
            "/OmniSurface/Shader"
        ):
            continue

        enable_specular_transmission = prim.GetAttribute(
            "inputs:enable_specular_transmission"
        )
        if enable_specular_transmission.IsValid():
            enable_specular_transmission.Set(False)

        specular_transmission_weight = prim.GetAttribute(
            "inputs:specular_transmission_weight"
        )
        if specular_transmission_weight.IsValid():
            specular_transmission_weight.Set(0.0)

        enable_diffuse_transmission = prim.GetAttribute(
            "inputs:enable_diffuse_transmission"
        )
        if enable_diffuse_transmission.IsValid():
            enable_diffuse_transmission.Set(False)

        enable_opacity = prim.GetAttribute("inputs:enable_opacity")
        if enable_opacity.IsValid():
            enable_opacity.Set(False)

        geometry_opacity = prim.GetAttribute("inputs:geometry_opacity")
        if geometry_opacity.IsValid():
            geometry_opacity.Set(1.0)

        patched_shader_paths.append(prim_path)

    if patched_shader_paths:
        print(
            f"[{status_label}] disabled transmissive robot material on "
            f"{len(patched_shader_paths)} OmniSurface shader(s).",
            flush=True,
        )


def _ensure_cloudxr_runtime_environment_defaults() -> None:
    """Populate common CloudXR/OpenXR env vars from ``~/.cloudxr`` when the shell has not set them."""

    cloudxr_root = Path.home() / ".cloudxr"
    manifest_candidates = (
        cloudxr_root / "openxr_cloudxr.json",
        cloudxr_root / "share" / "openxr" / "1" / "openxr_cloudxr.json",
    )
    manifest_path = next((path for path in manifest_candidates if path.is_file()), None)
    if manifest_path is not None:
        manifest_str = str(manifest_path)
        if not os.environ.get("XR_RUNTIME_JSON"):
            os.environ["XR_RUNTIME_JSON"] = manifest_str
        if not os.environ.get("OPENXR_RUNTIME_JSON"):
            os.environ["OPENXR_RUNTIME_JSON"] = manifest_str

    runtime_dir = cloudxr_root / "run"
    if runtime_dir.is_dir() and not os.environ.get("NV_CXR_RUNTIME_DIR"):
        os.environ["NV_CXR_RUNTIME_DIR"] = str(runtime_dir)


_XR_RUNTIME_UNAVAILABLE_PATTERNS = (
    "xr_error_form_factor_unavailable",
    "waiting for hmd",
    "xrgetsystem timed out",
    "requested extension 'xr_ext_hand_tracking' is not advertised",
    "failed to determine active runtime",
    "failed to load a runtime",
    "failed to create openxr instance",
)
_XR_RETRY_INTERVAL_S = 2.0


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))
        current = current.__cause__ or current.__context__


def _format_exception_chain(exc: BaseException) -> str:
    return " -> ".join(
        f"{type(error).__name__}: {error}" for error in _iter_exception_chain(exc)
    )


def _is_xr_runtime_unavailable_error(exc: BaseException) -> bool:
    for error in _iter_exception_chain(exc):
        message = f"{type(error).__name__}: {error}".lower()
        if any(pattern in message for pattern in _XR_RUNTIME_UNAVAILABLE_PATTERNS):
            return True
    return False


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
    translation_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation_offset_rpy_deg: tuple[float, float, float] = (90.0, 0.0, 90.0)
    horizontal_aperture_mm: float = 20.955
    focal_length_mm: float = 18.14756
    clipping_range_m: tuple[float, float] = (0.01, 1000.0)


@dataclass(frozen=True)
class HeadViewXrDisplayConfig:
    enabled: bool = False
    activate_on_calibration: bool = True
    app_name: str = "G1HeadViewXrDisplay"
    resolution_px: tuple[int, int] = (960, 540)
    lock_mode: str = "head"
    distance_m: float = 1.2
    offset_x_m: float = 0.0
    offset_y_m: float = 0.0
    plane_width_m: float = 2.2
    near_z_m: float = 0.05
    far_z_m: float = 100.0
    clear_color_rgba: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True)
class AuxiliaryViewportConfig:
    enabled: bool = True
    activate_on_calibration: bool = True
    window_name: str = "Teleop Default View"
    resolution_px: tuple[int, int] = (960, 540)
    position_px: tuple[int, int] = (40, 40)


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
        whole_body_yaw: Any | None,
    ) -> None:
        self._config = config
        self._viewport_api = viewport_api
        self._UsdGeom = UsdGeom
        self._Gf = Gf
        self._head_link_prim = head_link_prim
        self._avp_frame_binding = avp_frame_binding
        self._whole_body_yaw = whole_body_yaw
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
        if self._viewport_api is None or self._active:
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
        if avp_frame_binding is None or not getattr(
            avp_frame_binding, "calibrated", False
        ):
            return base_rotation
        camera_rotation = base_rotation

        try:
            tilt_delta_rot = avp_frame_binding.latest_head_tilt_delta_rot()
        except Exception:
            tilt_delta_rot = None
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

    return HeadViewCameraConfig(
        enabled=bool(camera_config.get("enabled", True)),
        activate_on_calibration=bool(
            camera_config.get("activate_on_calibration", True)
        ),
        prim_path=prim_path,
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


def _head_view_xr_display_config(config: Mapping[str, Any]) -> HeadViewXrDisplayConfig:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    xr_config = robot_config.get("head_view_xr_display", {})
    if xr_config is None:
        xr_config = {}
    if not isinstance(xr_config, Mapping):
        raise ValueError("Config field 'robot.head_view_xr_display' must be a mapping")

    resolution_values = xr_config.get("resolution_px", (960, 540))
    if isinstance(resolution_values, (str, bytes)) or not isinstance(
        resolution_values, Sequence
    ):
        raise ValueError(
            "Config field 'robot.head_view_xr_display.resolution_px' must be a sequence"
        )
    resolution_tuple = tuple(int(value) for value in resolution_values)
    if (
        len(resolution_tuple) != 2
        or resolution_tuple[0] <= 0
        or resolution_tuple[1] <= 0
    ):
        raise ValueError(
            "Config field 'robot.head_view_xr_display.resolution_px' must contain two positive integers"
        )

    lock_mode_raw = str(xr_config.get("lock_mode", "head")).strip().lower()
    lock_mode_aliases = {
        "head": "head",
        "head_locked": "head",
        "world": "world",
        "world_locked": "world",
    }
    lock_mode = lock_mode_aliases.get(lock_mode_raw, lock_mode_raw)
    if lock_mode not in {"head", "world"}:
        raise ValueError(
            "Config field 'robot.head_view_xr_display.lock_mode' must be 'head' or 'world'"
        )

    return HeadViewXrDisplayConfig(
        enabled=bool(xr_config.get("enabled", False)),
        activate_on_calibration=bool(xr_config.get("activate_on_calibration", True)),
        app_name=str(xr_config.get("app_name", "G1HeadViewXrDisplay")).strip()
        or "G1HeadViewXrDisplay",
        resolution_px=(resolution_tuple[0], resolution_tuple[1]),
        lock_mode=lock_mode,
        distance_m=float(xr_config.get("distance_m", 1.2)),
        offset_x_m=float(xr_config.get("offset_x_m", 0.0)),
        offset_y_m=float(xr_config.get("offset_y_m", 0.0)),
        plane_width_m=float(xr_config.get("plane_width_m", 2.2)),
        near_z_m=float(xr_config.get("near_z_m", 0.05)),
        far_z_m=float(xr_config.get("far_z_m", 100.0)),
        clear_color_rgba=_float_tuple(
            xr_config.get("clear_color_rgba"),
            name="robot.head_view_xr_display.clear_color_rgba",
            length=4,
            default=(0.0, 0.0, 0.0, 1.0),
        ),
    )


def _auxiliary_viewport_config(config: Mapping[str, Any]) -> AuxiliaryViewportConfig:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    aux_config = robot_config.get("auxiliary_viewport", {})
    if aux_config is None:
        aux_config = {}
    if not isinstance(aux_config, Mapping):
        raise ValueError("Config field 'robot.auxiliary_viewport' must be a mapping")

    resolution_values = aux_config.get("resolution_px", (960, 540))
    if isinstance(resolution_values, (str, bytes)) or not isinstance(
        resolution_values, Sequence
    ):
        raise ValueError(
            "Config field 'robot.auxiliary_viewport.resolution_px' must be a sequence"
        )
    resolution_tuple = tuple(int(value) for value in resolution_values)
    if (
        len(resolution_tuple) != 2
        or resolution_tuple[0] <= 0
        or resolution_tuple[1] <= 0
    ):
        raise ValueError(
            "Config field 'robot.auxiliary_viewport.resolution_px' must contain two positive integers"
        )

    position_values = aux_config.get("position_px", (40, 40))
    if isinstance(position_values, (str, bytes)) or not isinstance(
        position_values, Sequence
    ):
        raise ValueError(
            "Config field 'robot.auxiliary_viewport.position_px' must be a sequence"
        )
    position_tuple = tuple(int(value) for value in position_values)
    if len(position_tuple) != 2:
        raise ValueError(
            "Config field 'robot.auxiliary_viewport.position_px' must contain two integers"
        )

    return AuxiliaryViewportConfig(
        enabled=bool(aux_config.get("enabled", True)),
        activate_on_calibration=bool(aux_config.get("activate_on_calibration", True)),
        window_name=str(aux_config.get("window_name", "Teleop Default View")).strip()
        or "Teleop Default View",
        resolution_px=(resolution_tuple[0], resolution_tuple[1]),
        position_px=(position_tuple[0], position_tuple[1]),
    )


def _quat_wxyz_normalize(
    quat_wxyz: Sequence[float],
) -> tuple[float, float, float, float]:
    quat = np.asarray(quat_wxyz, dtype=np.float64)
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-8:
        return (1.0, 0.0, 0.0, 0.0)
    quat /= norm
    return tuple(float(value) for value in quat)


def _quat_wxyz_mul(
    lhs_wxyz: Sequence[float], rhs_wxyz: Sequence[float]
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = _quat_wxyz_normalize(lhs_wxyz)
    rw, rx, ry, rz = _quat_wxyz_normalize(rhs_wxyz)
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _quat_wxyz_rotate(
    quat_wxyz: Sequence[float], vector_xyz: Sequence[float]
) -> tuple[float, float, float]:
    qw, qx, qy, qz = _quat_wxyz_normalize(quat_wxyz)
    vector = np.asarray(vector_xyz, dtype=np.float64)
    qvec = np.asarray([qx, qy, qz], dtype=np.float64)
    uv = np.cross(qvec, vector)
    uuv = np.cross(qvec, uv)
    rotated = vector + 2.0 * (qw * uv + uuv)
    return tuple(float(value) for value in rotated)


def _yaw_quat_wxyz(yaw_rad: float) -> tuple[float, float, float, float]:
    return (
        float(np.cos(yaw_rad * 0.5)),
        0.0,
        float(np.sin(yaw_rad * 0.5)),
        0.0,
    )


class HeadViewXrDisplayBridge:
    """Present the robot head-view camera in the AVP headset via a shared XR session."""

    _IDENTITY_ROT_WXYZ = (1.0, 0.0, 0.0, 0.0)

    def __init__(
        self,
        *,
        config: HeadViewXrDisplayConfig,
        camera_prim_path: str,
        required_xr_extensions: Sequence[str],
        sim_device: str,
    ) -> None:
        ensure_import_paths()
        try:
            import isaacteleop.viz as viz
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "robot.head_view_xr_display requires isaacteleop.viz, but the Televiz "
                "Python module is not available. Rebuild IsaacTeleop with "
                "`cmake -B build-local -DBUILD_VIZ=ON && cmake --build build-local "
                "--target python_wheel` so isaacteleop.viz._viz is produced."
            ) from exc

        try:
            from isaacteleop.oxr import OpenXRSessionHandles
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "robot.head_view_xr_display requires isaacteleop.oxr to share the XR session."
            ) from exc

        if not str(sim_device).startswith("cuda"):
            raise ValueError(
                "robot.head_view_xr_display currently requires a CUDA Isaac Sim device"
            )

        rep = _import_omni_replicator_core()
        self._config = config
        self._camera_prim_path = str(camera_prim_path)
        self._rep = rep
        self._viz = viz
        self._capture_device = str(sim_device)
        self._visible = False
        self._render_product = None
        self._rgb_annotator = None
        self._render_error: BaseException | None = None
        self._stop = threading.Event()
        self._render_thread: threading.Thread | None = None
        self._world_locked_pose: (
            tuple[
                tuple[float, float, float],
                tuple[float, float, float, float],
            ]
            | None
        ) = None
        self._plane_size_m = (
            float(config.plane_width_m),
            float(config.plane_width_m)
            * float(config.resolution_px[1])
            / float(config.resolution_px[0]),
        )

        session_cfg = viz.VizSessionConfig()
        session_cfg.mode = viz.DisplayMode.kXr
        session_cfg.app_name = config.app_name
        session_cfg.xr_near_z = float(config.near_z_m)
        session_cfg.xr_far_z = float(config.far_z_m)
        session_cfg.required_extensions = list(required_xr_extensions)
        session_cfg.clear_color = tuple(
            float(value) for value in config.clear_color_rgba
        )
        self._viz_session = viz.VizSession.create(session_cfg)

        oxr_handles_tuple = self._viz_session.get_oxr_handles()
        if oxr_handles_tuple is None:
            raise RuntimeError(
                "Televiz XR session was created, but no OpenXR handles were exposed for TeleopSession sharing."
            )
        self._oxr_handles = OpenXRSessionHandles(*oxr_handles_tuple)

        layer_cfg = viz.QuadLayerConfig()
        layer_cfg.name = "robot_head_view_xr"
        layer_cfg.resolution = viz.Resolution(
            int(config.resolution_px[0]), int(config.resolution_px[1])
        )
        layer_cfg.format = viz.PixelFormat.kRGBA8
        layer_cfg.placement = self._initial_placement()
        self._layer = self._viz_session.add_quad_layer(layer_cfg)
        self._layer.set_visible(False)
        self._create_camera_render_product()

        self._render_thread = threading.Thread(
            target=self._render_loop,
            name="g1_head_view_xr_render",
            daemon=False,
        )
        self._render_thread.start()

    @property
    def oxr_handles(self) -> Any:
        return self._oxr_handles

    def set_visible(self, visible: bool) -> None:
        self._raise_if_failed()
        new_visible = bool(visible)
        if new_visible == self._visible:
            return
        self._layer.set_visible(new_visible)
        self._visible = new_visible

    def submit_frame(self) -> bool:
        self._raise_if_failed()
        rgba = self._read_camera_frame()
        if rgba is None:
            return False
        self._layer.submit(self._coerce_cuda_image(rgba))
        return True

    def close(self) -> None:
        self._stop.set()
        if self._render_thread is not None:
            self._render_thread.join(timeout=5.0)
            if self._render_thread.is_alive():
                print(
                    "Head-view XR display render thread did not exit within 5s; "
                    "skipping explicit Televiz destruction to avoid tearing down an active XR session.",
                    flush=True,
                )
            else:
                self._render_thread = None
        self._destroy_camera_render_product()
        if self._render_thread is None:
            viz_session = getattr(self, "_viz_session", None)
            if viz_session is not None:
                viz_session.destroy()
                self._viz_session = None
        if self._render_error is not None:
            print(
                f"Head-view XR display render loop stopped with error: {self._render_error}",
                file=sys.stderr,
                flush=True,
            )

    def _raise_if_failed(self) -> None:
        if self._render_error is not None:
            raise RuntimeError(
                f"Head-view XR display render loop failed: {self._render_error}"
            ) from self._render_error

    def _create_camera_render_product(self) -> None:
        try:
            self._render_product = self._rep.create.render_product(
                self._camera_prim_path,
                (
                    int(self._config.resolution_px[0]),
                    int(self._config.resolution_px[1]),
                ),
                force_new=True,
            )
            self._rgb_annotator = self._rep.AnnotatorRegistry.get_annotator(
                "LdrColor",
                device="cuda",
                do_array_copy=False,
            )
            self._rgb_annotator.attach(self._render_product)
        except Exception:
            self._destroy_camera_render_product()
            raise

    def _destroy_camera_render_product(self) -> None:
        annotator = getattr(self, "_rgb_annotator", None)
        if annotator is not None:
            try:
                annotator.detach()
            except Exception:
                pass
            self._rgb_annotator = None
        render_product = getattr(self, "_render_product", None)
        if render_product is not None:
            try:
                render_product.destroy()
            except Exception:
                pass
            self._render_product = None

    def _read_camera_frame(self) -> Any | None:
        if self._stop.is_set():
            return None
        annotator = self._rgb_annotator
        if annotator is None:
            return None
        try:
            rgba = annotator.get_data(device="cuda")
        except Exception as exc:
            self._render_error = exc
            raise
        if rgba is None:
            return None
        if isinstance(rgba, Mapping):
            rgba = rgba.get("data")
        if rgba is None:
            return None
        try:
            import warp as wp

            # Replicator commonly returns a Warp CUDA array here. Converting once
            # to Torch normalizes vec4-vs-last-dimension layouts and avoids Warp's
            # Python indexing limitations (for example ``[..., :4]``).
            if isinstance(rgba, wp.array):
                rgba = wp.to_torch(rgba)
        except Exception:
            pass
        shape = tuple(int(dim) for dim in getattr(rgba, "shape", ()))
        # Freshly attached render products often need a few rendered frames before
        # LdrColor exposes a real HxWxC image. Treat that warm-up window as
        # "frame not ready yet" instead of tearing down the teleop session.
        if len(shape) < 3 or shape[0] <= 0 or shape[1] <= 0 or shape[-1] < 4:
            return None
        if shape[-1] == 4:
            return rgba
        return rgba[..., :4]

    def _coerce_cuda_image(self, image: Any) -> Any:
        if hasattr(image, "__cuda_array_interface__"):
            return image
        if hasattr(image, "__dlpack__"):
            try:
                import warp as wp

                converted = wp.to_torch(image)
                if hasattr(converted, "__cuda_array_interface__"):
                    return converted
            except Exception:
                pass
        if hasattr(image, "__array_interface__"):
            import torch

            return torch.as_tensor(
                np.asarray(image), device=self._capture_device
            ).contiguous()
        raise TypeError(
            "Head-view XR display received a camera frame that does not expose "
            "__cuda_array_interface__ or __array_interface__."
        )

    def _initial_placement(self) -> Any:
        return self._viz.QuadLayerPlacement(
            self._viz.Pose3D(
                (0.0, 1.5, -float(self._config.distance_m)),
                self._IDENTITY_ROT_WXYZ,
            ),
            self._plane_size_m,
        )

    def _render_loop(self) -> None:
        try:
            while not self._stop.is_set():
                self._update_layer_placement()
                self._viz_session.render()
                if self._viz_session.should_close():
                    self._stop.set()
        except BaseException as exc:
            self._render_error = exc
            self._stop.set()

    def _update_layer_placement(self) -> None:
        head_pose = self._viz_session.head_pose_now()
        if head_pose is None:
            return
        head_position = tuple(float(value) for value in head_pose.position)
        head_orientation = tuple(float(value) for value in head_pose.orientation)
        if self._config.lock_mode == "world":
            if self._world_locked_pose is None:
                self._world_locked_pose = self._compute_world_locked_pose(
                    head_position, head_orientation
                )
            position, orientation = self._world_locked_pose
        else:
            position, orientation = self._compute_head_locked_pose(
                head_position, head_orientation
            )
        self._layer.set_placement(
            self._viz.QuadLayerPlacement(
                self._viz.Pose3D(position, orientation),
                self._plane_size_m,
            )
        )

    def _compute_head_locked_pose(
        self,
        head_position: tuple[float, float, float],
        head_orientation: tuple[float, float, float, float],
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float, float],
    ]:
        forward = _quat_wxyz_rotate(head_orientation, (0.0, 0.0, -1.0))
        right = _quat_wxyz_rotate(head_orientation, (1.0, 0.0, 0.0))
        up = _quat_wxyz_rotate(head_orientation, (0.0, 1.0, 0.0))
        position = (
            head_position[0]
            + forward[0] * self._config.distance_m
            + right[0] * self._config.offset_x_m
            + up[0] * self._config.offset_y_m,
            head_position[1]
            + forward[1] * self._config.distance_m
            + right[1] * self._config.offset_x_m
            + up[1] * self._config.offset_y_m,
            head_position[2]
            + forward[2] * self._config.distance_m
            + right[2] * self._config.offset_x_m
            + up[2] * self._config.offset_y_m,
        )
        orientation = _quat_wxyz_mul(head_orientation, self._IDENTITY_ROT_WXYZ)
        return position, orientation

    def _compute_world_locked_pose(
        self,
        head_position: tuple[float, float, float],
        head_orientation: tuple[float, float, float, float],
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float, float],
    ]:
        forward = np.asarray(
            _quat_wxyz_rotate(head_orientation, (0.0, 0.0, -1.0)),
            dtype=np.float64,
        )
        forward[1] = 0.0
        forward_norm = float(np.linalg.norm(forward))
        if forward_norm <= 1e-8:
            forward = np.asarray([0.0, 0.0, -1.0], dtype=np.float64)
        else:
            forward /= forward_norm
        right = np.asarray([-forward[2], 0.0, forward[0]], dtype=np.float64)
        position = (
            head_position[0]
            + float(forward[0]) * self._config.distance_m
            + float(right[0]) * self._config.offset_x_m,
            head_position[1] + self._config.offset_y_m,
            head_position[2]
            + float(forward[2]) * self._config.distance_m
            + float(right[2]) * self._config.offset_x_m,
        )
        yaw = float(
            np.arctan2(head_position[0] - position[0], head_position[2] - position[2])
        )
        return position, _quat_wxyz_mul(_yaw_quat_wxyz(yaw), self._IDENTITY_ROT_WXYZ)


class AuxiliaryViewportController:
    """Manage a secondary viewport that preserves the scene's initial camera view."""

    def __init__(
        self,
        *,
        config: AuxiliaryViewportConfig,
        viewport_utility: Any,
        initial_camera_path: str | None,
    ) -> None:
        self._config = config
        self._viewport_utility = viewport_utility
        self._initial_camera_path = (
            None if initial_camera_path is None else str(initial_camera_path)
        )
        self._window = None

    def show(self) -> None:
        if not self._initial_camera_path:
            return
        if self._window is None:
            self._window = self._viewport_utility.create_viewport_window(
                name=self._config.window_name,
                width=int(self._config.resolution_px[0]),
                height=int(self._config.resolution_px[1]),
                position_x=int(self._config.position_px[0]),
                position_y=int(self._config.position_px[1]),
                camera_path=self._initial_camera_path,
            )
            self._dock_to_main_viewport_async()
        if self._window is None:
            return
        self._window.viewport_api.camera_path = self._initial_camera_path
        self._window.visible = True

    def hide(self) -> None:
        if self._window is not None:
            self._window.visible = False

    def close(self) -> None:
        window = self._window
        self._window = None
        if window is None:
            return
        try:
            window.visible = False
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass

    def _dock_to_main_viewport_async(self) -> None:
        window = self._window
        if window is None:
            return

        async def dock_window() -> None:
            try:
                import omni.ui as ui
                import omni.kit.app

                await omni.kit.app.get_app().next_update_async()
                main_viewport = ui.Workspace.get_window("Viewport")
                if main_viewport is not None and window is not None:
                    window.dock_in(main_viewport, ui.DockPosition.RIGHT, 0.35)
            except Exception:
                pass

        try:
            asyncio.ensure_future(dock_window())
        except Exception:
            pass


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
    marker_scale: float | None = None
    marker_z_offset: float | None = None
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


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyYAML is required to load the teleop config file."
        ) from exc

    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


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

    # The first version of this config key was misnamed as wxyz. Keep it as a
    # short-term alias, but IsaacLab's root InitialStateCfg.rot is xyzw here.
    raw_quat = robot_config.get("initial_world_orientation_xyzw")
    if raw_quat is None:
        raw_quat = robot_config.get("initial_world_orientation_wxyz")
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
        marker_scale=None,
        marker_z_offset=None,
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


def _use_native_hand_targets(config: Mapping[str, Any]) -> bool:
    retargeting_config = config.get("retargeting", {})
    if retargeting_config is None:
        retargeting_config = {}
    if not isinstance(retargeting_config, Mapping):
        raise ValueError("Config field 'retargeting' must be a mapping")

    method = retargeting_config.get("method")
    if method is not None:
        normalized_method = str(method).strip().lower()
        aliases = {
            "native": "native_dex",
            "native_dex": "native_dex",
            "dex": "native_dex",
            "dexhand": "native_dex",
            "dex_hand": "native_dex",
            "official": "official_wuji",
            "official_wuji": "official_wuji",
            "wuji": "official_wuji",
        }
        normalized_method = aliases.get(normalized_method, normalized_method)
        if normalized_method == "native_dex":
            return True
        if normalized_method == "official_wuji":
            return False
        raise ValueError(
            "Config field 'retargeting.method' must be one of "
            "['native_dex', 'official_wuji']"
        )

    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")
    return bool(robot_config.get("use_native_hand_retargeting", False))


def _load_isaac_lab():
    try:
        from isaaclab.app import AppLauncher
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Isaac Lab Python modules were not found. "
            "Run this script with Isaac Lab's Python environment, "
            "for example /home/lightwheel/workspace/isaaclab/env_isaaclab/bin/python."
        ) from exc

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
        import warp as wp
        from isaaclab.controllers import DifferentialIKController
        from isaaclab.controllers.differential_ik_cfg import DifferentialIKControllerCfg
        from isaaclab.utils import math as math_utils

        self._robot = robot
        self._config = config
        self._pose_binding = pose_binding
        self._device = device
        self._torch = torch
        self._wp = wp
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
        self._last_target_poses_root: dict[str, tuple[Any, Any]] = {}
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
            if getattr(robot, "is_fixed_base", False):
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
        ee_pos_w = self._wp.to_torch(self._robot.data.body_pos_w)[:, body_idx]
        ee_quat_w = self._wp.to_torch(self._robot.data.body_quat_w)[:, body_idx]
        root_pos_w = self._wp.to_torch(self._robot.data.root_pos_w)
        root_quat_w = self._wp.to_torch(self._robot.data.root_quat_w)
        ee_pos_b, ee_quat_b = self._math_utils.subtract_frame_transforms(
            root_pos_w, root_quat_w, ee_pos_w, ee_quat_w
        )
        return self._math_utils.combine_frame_transforms(
            ee_pos_b,
            ee_quat_b,
            self._offset_pos[side],
            self._offset_rot[side],
        )

    def frame_pose_world_np(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        poses: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for side in ("left", "right"):
            body_idx = self._body_ids[side]
            body_pos = self._wp.to_torch(self._robot.data.body_pos_w)[:, body_idx]
            body_quat = self._wp.to_torch(self._robot.data.body_quat_w)[:, body_idx]
            pos_w, quat_w = self._math_utils.combine_frame_transforms(
                body_pos,
                body_quat,
                self._offset_pos[side],
                self._offset_rot[side],
            )
            rot_w = self._math_utils.matrix_from_quat(quat_w)
            poses[side] = (
                pos_w[0].detach().cpu().numpy().astype(np.float32),
                rot_w[0].detach().cpu().numpy().astype(np.float32),
            )
        return poses

    def target_pose_world_np(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        poses: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        root_pos_w = self._wp.to_torch(self._robot.data.root_pos_w)
        root_quat_w = self._wp.to_torch(self._robot.data.root_quat_w)
        for side, target_pose_root in self._last_target_poses_root.items():
            pos_b, quat_b = target_pose_root
            pos_w, quat_w = self._math_utils.combine_frame_transforms(
                root_pos_w,
                root_quat_w,
                pos_b,
                quat_b,
            )
            rot_w = self._math_utils.matrix_from_quat(quat_w)
            poses[side] = (
                pos_w[0].detach().cpu().numpy().astype(np.float32),
                rot_w[0].detach().cpu().numpy().astype(np.float32),
            )
        return poses

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
                scale=1.0
                if self._config.marker_scale is None
                else self._config.marker_scale,
                offset_z=0.0
                if self._config.marker_z_offset is None
                else self._config.marker_z_offset,
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
        root_pos_w = self._wp.to_torch(self._robot.data.root_pos_w)
        root_quat_w = self._wp.to_torch(self._robot.data.root_quat_w)
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
        jacobian = self._wp.to_torch(self._robot.root_physx_view.get_jacobians())[
            :, self._jacobi_body_ids[side], :, self._jacobi_joint_ids[side]
        ].clone()
        root_quat_w = self._wp.to_torch(self._robot.data.root_quat_w)
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
        self._last_target_poses_root[side] = (
            self._controllers[side].ee_pos_des.detach().clone(),
            self._controllers[side].ee_quat_des.detach().clone(),
        )
        joint_pos = self._wp.to_torch(self._robot.data.joint_pos)[
            :, self._joint_ids[side]
        ]
        joint_targets = self._compute_joint_targets(
            side,
            ee_pos_curr,
            ee_quat_curr,
            joint_pos,
        )

        if self._config.clamp_to_joint_limits:
            limits = self._wp.to_torch(self._robot.data.soft_joint_pos_limits)[
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
        self._robot.set_joint_position_target_index(
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
                    self._robot.set_joint_position_target_index(
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
        self._last_target_poses_root.clear()
        print(
            f"[{self._config.status_label}] arm IK startup target references cleared; "
            "waiting for re-arm calibration.",
            flush=True,
        )


class WholeBodyYawController:
    """Rotate the robot base with the calibrated head yaw around the AVP z-axis."""

    def __init__(
        self,
        robot: Any,
        config: AvpFrameBindingRuntimeConfig,
        *,
        device: str,
    ) -> None:
        import torch
        import warp as wp

        self._robot = robot
        self._config = config
        self._device = device
        self._torch = torch
        self._wp = wp
        self._joint_id, self._joint_name = self._find_base_yaw_joint()
        self._joint_limits = self._joint_limits_np()
        self._reference_target = self._current_joint_pos()
        self._last_target = self._reference_target
        print(
            f"[{self._config.status_label}] whole-body yaw following active: "
            f"joint={self._joint_name!r}, "
            f"deadband_rad={self._config.whole_body_yaw_deadband_rad:.3f}, "
            f"smoothing_alpha={self._config.whole_body_yaw_smoothing_alpha:.2f}.",
            flush=True,
        )

    @property
    def joint_id(self) -> int:
        return self._joint_id

    def _find_base_yaw_joint(self) -> tuple[int, str]:
        available = tuple(
            str(name) for name in (getattr(self._robot.data, "joint_names", ()) or ())
        )
        for candidate in ("base_yaw", "base_yaw_joint"):
            if candidate in available:
                return available.index(candidate), candidate

        fuzzy = [
            (index, name)
            for index, name in enumerate(available)
            if "base" in name.lower() and "yaw" in name.lower()
        ]
        if len(fuzzy) == 1:
            return fuzzy[0]

        raise RuntimeError(
            f"Could not resolve the {self._config.status_label} base yaw joint. "
            f"Candidates={fuzzy[:8]} available_first={list(available[:40])}"
        )

    def _joint_limits_np(self) -> tuple[float, float] | None:
        try:
            limits = self._wp.to_torch(self._robot.data.soft_joint_pos_limits)
            values = limits[0, self._joint_id].detach().cpu().numpy()
        except Exception:
            return None
        if np.asarray(values).shape != (2,):
            return None
        return float(values[0]), float(values[1])

    def _current_joint_pos(self) -> float:
        joint_pos = self._wp.to_torch(self._robot.data.joint_pos)
        return float(joint_pos[0, self._joint_id].detach().cpu().item())

    def _apply_target(self, target_value: float) -> None:
        target_tensor = self._torch.tensor(
            [[float(target_value)]],
            dtype=self._torch.float32,
            device=self._device,
        )
        self._robot.set_joint_position_target_index(
            target=target_tensor,
            joint_ids=[self._joint_id],
        )

    def reset_reference(self) -> None:
        current = self._current_joint_pos()
        self._reference_target = current
        self._last_target = current
        self._apply_target(current)

    def hold_current_target(self) -> None:
        self._apply_target(self._last_target)

    def current_yaw_delta_rad(self) -> float:
        return float(self._current_joint_pos() - self._reference_target)

    def update(self, pose_binding: AvpRobotFrameBinding | None) -> None:
        if pose_binding is None or not pose_binding.whole_body_yaw_following_enabled:
            return

        target_value = self._reference_target + pose_binding.latest_head_yaw_delta_rad()
        if self._joint_limits is not None:
            target_value = float(
                np.clip(target_value, self._joint_limits[0], self._joint_limits[1])
            )

        alpha = self._config.whole_body_yaw_smoothing_alpha
        target_value = self._last_target * (1.0 - alpha) + target_value * alpha
        self._last_target = float(target_value)
        self._apply_target(self._last_target)


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


def _configured_initial_positions(
    joint_names: Sequence[str], config: WujiHandRuntimeConfig
) -> np.ndarray:
    return np.asarray(
        [
            config.initial_joint_positions.get(name, config.initial_joint_position)
            for name in joint_names
        ],
        dtype=np.float32,
    )


def _default_joint_positions(
    robot: Any,
    joint_ids: Sequence[int],
    joint_names: Sequence[str],
    config: WujiHandRuntimeConfig,
) -> np.ndarray:
    try:
        import warp as wp

        default_joint_pos = wp.to_torch(robot.data.default_joint_pos)
        values = default_joint_pos[0, list(joint_ids)].detach().cpu().numpy()
        return values.astype(np.float32)
    except Exception:
        return _configured_initial_positions(joint_names, config)


def _soft_joint_limits(robot: Any, joint_ids: Sequence[int]) -> np.ndarray | None:
    try:
        import warp as wp

        limits = wp.to_torch(robot.data.soft_joint_pos_limits)
        values = limits[0, list(joint_ids), :].detach().cpu().numpy()
        if values.shape != (len(joint_ids), 2):
            return None
        return values.astype(np.float32)
    except Exception:
        return None


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    AppLauncher = _load_isaac_lab()
    parser = argparse.ArgumentParser(
        description="Run a minimal G1 Isaac Lab scene driven by AVP + MANUS teleop."
    )
    parser.add_argument("--config", default=str(_default_config_path()))
    parser.add_argument("--robot-usd", default=None)
    parser.add_argument("--robot-prim", default=None)
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument("--wrist-marker-scale", type=float, default=1.0)
    parser.add_argument("--wrist-marker-z-offset", type=float, default=0.0)
    parser.add_argument("--wrist-marker-radius", type=float, default=0.045)
    parser.add_argument("--wrist-axis-length", type=float, default=0.18)
    parser.add_argument("--wrist-axis-radius", type=float, default=0.008)
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
    ensure_import_paths()
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config_path = Path(args.config).expanduser().resolve()
    teleop_config = _load_yaml_file(config_path)
    teleop_config["_config_dir"] = str(config_path.parent)
    robot_profile = robot_profile_from_config(teleop_config)
    status_label = robot_profile.status_label
    use_native_hand_targets = _use_native_hand_targets(teleop_config)
    head_view_camera_config = _head_view_camera_config(teleop_config)
    head_view_xr_display_config = _head_view_xr_display_config(teleop_config)
    auxiliary_viewport_config = _auxiliary_viewport_config(teleop_config)
    initial_world_position = _robot_initial_world_position(teleop_config)
    initial_world_orientation_xyzw = _robot_initial_world_orientation_xyzw(
        teleop_config
    )
    wuji_hand_config = wuji_hand_runtime_config(teleop_config)
    arm_ik_config = _arm_ik_runtime_config(teleop_config)
    avp_frame_binding_config = avp_frame_binding_runtime_config(teleop_config)
    arm_ik_config = dataclass_replace(
        arm_ik_config,
        marker_scale=(
            args.wrist_marker_scale
            if arm_ik_config.marker_scale is None
            else arm_ik_config.marker_scale
        ),
        marker_z_offset=(
            args.wrist_marker_z_offset
            if arm_ik_config.marker_z_offset is None
            else arm_ik_config.marker_z_offset
        ),
    )
    if args.robot_height is not None:
        initial_world_position = (
            initial_world_position[0],
            initial_world_position[1],
            float(args.robot_height),
        )
    robot_usd = (
        Path(args.robot_usd).expanduser().resolve()
        if args.robot_usd
        else resolve_repo_relative_path(robot_profile.default_usd_relpath)
    )
    if not robot_usd.is_file():
        raise FileNotFoundError(f"{status_label} USD not found: {robot_usd}")
    robot_prim = str(args.robot_prim or robot_profile.robot_prim)

    AppLauncher = _load_isaac_lab()
    app_launcher = AppLauncher(args)
    simulation_app = app_launcher.app
    _ensure_cloudxr_runtime_environment_defaults()

    import carb
    import omni.usd
    import torch
    from isaaclab.markers import VisualizationMarkers, VisualizationMarkersCfg
    from pxr import Gf, UsdGeom

    import isaaclab.sim as sim_utils
    from isaaclab.sim import SimulationContext

    _ensure_carb_input_available()
    omni_appwindow = _import_omni_appwindow()
    omni_viewport_utility = _import_omni_viewport_utility()

    sim_cfg = sim_utils.SimulationCfg(dt=1.0 / 60.0, device=args.device)
    sim = SimulationContext(sim_cfg)
    sim.set_camera_view([3.0, -4.0, 2.0], [0.0, 0.0, 0.9])

    scene_config = G1WujiSceneConfig(
        robot_prim=robot_prim,
        robot_usd=robot_usd,
        initial_world_position=initial_world_position,
        initial_world_orientation_xyzw=initial_world_orientation_xyzw,
        initial_hand_joint_positions=wuji_hand_config.initial_joint_positions,
        light_intensity=args.light_intensity,
    )
    robot = design_g1_wuji_scene(scene_config)
    debug_viz_config = debug_viz_runtime_config(teleop_config)
    debug_viz = create_debug_viz(
        sim_utils=sim_utils,
        VisualizationMarkers=VisualizationMarkers,
        VisualizationMarkersCfg=VisualizationMarkersCfg,
        scene_config=DebugVizSceneConfig(
            wrist_marker_radius=args.wrist_marker_radius,
            wrist_axis_length=args.wrist_axis_length,
            wrist_axis_radius=args.wrist_axis_radius,
            robot_z=float(initial_world_position[2]),
        ),
        runtime_config=debug_viz_config,
    )

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
        robot, left_joint_ids, wuji_hand_config.left_joint_names, wuji_hand_config
    )
    right_initial_targets = _default_joint_positions(
        robot, right_joint_ids, wuji_hand_config.right_joint_names, wuji_hand_config
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
    wuji_backend = (
        None if use_native_hand_targets else WujiHandTargetBackend(wuji_hand_config)
    )
    avp_frame_binding = (
        AvpRobotFrameBinding(
            robot,
            arm_ik_config,
            avp_frame_binding_config,
            marker_scale=1.0
            if arm_ik_config.marker_scale is None
            else arm_ik_config.marker_scale,
            marker_z_offset=0.0
            if arm_ik_config.marker_z_offset is None
            else arm_ik_config.marker_z_offset,
        )
        if avp_frame_binding_config.enabled
        else None
    )
    whole_body_yaw = (
        WholeBodyYawController(
            robot,
            avp_frame_binding_config,
            device=sim.device,
        )
        if avp_frame_binding_config.enabled
        and avp_frame_binding_config.whole_body_yaw_following
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
    robot_root_prim = stage.GetPrimAtPath(robot_prim) if stage is not None else None
    _disable_robot_transmissive_materials(
        stage=stage,
        robot_root_prim=robot_root_prim,
        status_label=status_label,
    )
    head_link_prim = (
        find_head_like_prim(stage, robot_root_prim, robot_prim)
        if robot_root_prim is not None and robot_root_prim.IsValid()
        else None
    )
    if head_link_prim is None:
        head_candidates = []
        if robot_root_prim is not None and robot_root_prim.IsValid():
            head_candidates = [
                str(prim.GetPath())
                for prim in walk_child_prims(robot_root_prim)
                if "head" in prim.GetName().lower()
            ][:8]
        print(
            f"[{status_label}] warning: could not find a head-like prim under {robot_prim}; "
            f"candidates={head_candidates}.",
            flush=True,
        )
    else:
        print(
            f"[{status_label}] head point visualization uses prim {head_link_prim.GetPath()}",
            flush=True,
        )
    xform_cache = UsdGeom.XformCache()
    viewport_api = omni_viewport_utility.get_active_viewport()
    default_viewport_camera_path = (
        str(viewport_api.camera_path)
        if viewport_api is not None
        and getattr(viewport_api, "camera_path", None) is not None
        else None
    )
    auxiliary_viewport = AuxiliaryViewportController(
        config=auxiliary_viewport_config,
        viewport_utility=omni_viewport_utility,
        initial_camera_path=default_viewport_camera_path,
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
            whole_body_yaw=whole_body_yaw,
        )
        if head_view_camera_config.enabled and stage is not None
        else None
    )
    teleop: TeleopMain | None = None
    teleop_started = False
    head_view_xr_display: HeadViewXrDisplayBridge | None = None
    scene_warmed_up = False
    xr_waiting_announced = False
    next_xr_retry_time = 0.0
    if head_view_xr_display_config.enabled and not args.scene_only:
        if head_view_camera is None:
            raise ValueError(
                "robot.head_view_xr_display.enabled requires robot.head_view_camera.enabled "
                "so there is a camera prim to publish into AVP."
            )
    import warp as wp

    robot_default_joint_pos = wp.to_torch(robot.data.default_joint_pos).clone()
    robot_default_joint_vel = wp.to_torch(robot.data.default_joint_vel).clone()
    robot.set_joint_position_target_index(
        target=torch.as_tensor(left_initial_targets, device=sim.device).unsqueeze(0),
        joint_ids=left_joint_ids,
    )
    robot.set_joint_position_target_index(
        target=torch.as_tensor(right_initial_targets, device=sim.device).unsqueeze(0),
        joint_ids=right_joint_ids,
    )

    print(
        f"{status_label} teleop scene ready: "
        f"{len(left_joint_ids)} left hand joints, {len(right_joint_ids)} right hand joints, "
        f"hand_retarget={'native_dex' if use_native_hand_targets else wuji_hand_config.retarget_backend}, "
        f"arm_ik={arm_ik_config.enabled}, "
        f"avp_frame_binding={avp_frame_binding_config.enabled}, "
        f"whole_body_yaw={whole_body_yaw is not None}, "
        f"head_view_camera={head_view_camera is not None}, "
        f"head_view_xr_display={head_view_xr_display_config.enabled and not args.scene_only}, "
        f"auxiliary_viewport={auxiliary_viewport_config.enabled and not args.scene_only}."
    )

    def step_scene_once(
        *,
        target_poses: Mapping[str, tuple[np.ndarray, np.ndarray]] | None = None,
        update_ee_frames: bool = False,
    ) -> None:
        if target_poses is not None:
            update_wrist_markers(
                debug_viz.wrist_markers,
                debug_viz.wrist_frames,
                target_poses,
                args.wrist_axis_length,
            )
        robot.write_data_to_sim()
        sim.step(render=sim.is_rendering)
        robot.update(sim_dt)
        if head_view_camera is not None:
            head_view_camera.update(xform_cache=xform_cache)
        if head_view_xr_display is not None:
            head_view_xr_display.submit_frame()
        update_head_marker(
            debug_viz,
            head_link_prim=head_link_prim,
            xform_cache=xform_cache,
        )
        if update_ee_frames and arm_ik is not None:
            ee_frame_poses = arm_ik.frame_pose_world_np()
            update_frame_axis_markers(
                debug_viz.robot_ee_frames,
                ee_frame_poses,
                args.wrist_axis_length,
            )

    if args.scene_only:
        print("Scene-only mode: OpenXR/MANUS teleop is not started.")
        start_time = time.monotonic()
        try:
            while simulation_app.is_running():
                if (
                    args.duration_s > 0.0
                    and time.monotonic() - start_time >= args.duration_s
                ):
                    break
                step_scene_once()
        finally:
            simulation_app.close()
        return 0

    if debug_viz_config.enabled:
        print(
            "Debug visualization is enabled and controlled by robot.debug_visualization."
        )

    marker_target_poses: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    teleop_armed = False
    start_waiting_announced = False
    keyboard_start_requested = False
    keyboard_reset_requested = False

    app_window = omni_appwindow.get_default_app_window()
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
        robot.set_joint_position_target_index(
            target=torch.as_tensor(left_initial_targets, device=sim.device).unsqueeze(
                0
            ),
            joint_ids=left_joint_ids,
        )
        robot.set_joint_position_target_index(
            target=torch.as_tensor(right_initial_targets, device=sim.device).unsqueeze(
                0
            ),
            joint_ids=right_joint_ids,
        )
        if whole_body_yaw is not None:
            whole_body_yaw.hold_current_target()

    def restore_robot_initial_pose() -> None:
        if hasattr(robot, "write_joint_state_to_sim"):
            robot.write_joint_state_to_sim(
                robot_default_joint_pos,
                robot_default_joint_vel,
            )
        robot.set_joint_position_target_index(
            target=robot_default_joint_pos,
        )
        if whole_body_yaw is not None:
            whole_body_yaw.reset_reference()
        if arm_ik is not None:
            arm_ik._last_targets.clear()

    def reset_teleop_calibration() -> None:
        if avp_frame_binding is not None:
            avp_frame_binding.reset_calibration()
        if whole_body_yaw is not None:
            whole_body_yaw.reset_reference()
        if arm_ik is not None:
            arm_ik.reset_startup_references()
        if head_view_camera is not None:
            head_view_camera.deactivate()
            if viewport_api is not None and default_viewport_camera_path:
                viewport_api.camera_path = default_viewport_camera_path
        if auxiliary_viewport_config.activate_on_calibration:
            auxiliary_viewport.hide()
        if (
            head_view_xr_display is not None
            and head_view_xr_display_config.activate_on_calibration
        ):
            head_view_xr_display.set_visible(False)

    def marker_pose_resolver(
        side: str,
        pose: Mapping[str, Any],
    ) -> tuple[np.ndarray, np.ndarray] | None:
        target_pose = marker_target_poses.get(side)
        if target_pose is not None:
            return target_pose
        return resolve_avp_marker_pose(
            side,
            pose,
            marker_scale=args.wrist_marker_scale,
            marker_z_offset=args.wrist_marker_z_offset,
            pose_binding=avp_frame_binding,
        )

    def close_openxr_runtime() -> None:
        nonlocal teleop, teleop_started, head_view_xr_display
        if teleop_started and teleop is not None:
            try:
                teleop.__exit__(None, None, None)
            except Exception:
                pass
        teleop = None
        teleop_started = False
        if head_view_xr_display is not None:
            try:
                head_view_xr_display.close()
            except Exception:
                pass
            head_view_xr_display = None
        auxiliary_viewport.close()

    def enter_xr_waiting_state(exc: BaseException, *, phase: str) -> None:
        nonlocal teleop_armed, start_waiting_announced, marker_target_poses
        nonlocal xr_waiting_announced, next_xr_retry_time
        close_openxr_runtime()
        teleop_armed = False
        start_waiting_announced = False
        marker_target_poses = {}
        restore_robot_initial_pose()
        reset_teleop_calibration()
        next_xr_retry_time = time.monotonic() + _XR_RETRY_INTERVAL_S
        if not xr_waiting_announced:
            print(
                f"[{status_label}] OpenXR {phase} is not ready: "
                f"{_format_exception_chain(exc)}. "
                "The scene will keep running while waiting for the HMD/runtime. "
                "Connect the headset or start the XR runtime, then wait for the "
                "automatic retry or press keyboard B to retry immediately.",
                flush=True,
            )
            xr_waiting_announced = True

    def try_start_openxr_runtime() -> bool:
        nonlocal teleop, teleop_started, head_view_xr_display
        nonlocal xr_waiting_announced, next_xr_retry_time
        was_waiting = xr_waiting_announced
        candidate_teleop = TeleopMain.from_config_file(config_path)
        candidate_head_view_xr_display: HeadViewXrDisplayBridge | None = None
        try:
            if head_view_xr_display_config.enabled:
                head_view_preflight_error = _head_view_xr_display_preflight_error(
                    head_view_camera.camera_path
                )
                if head_view_preflight_error is not None:
                    print(
                        f"[{status_label}] warning: disabling AVP head-view XR display "
                        "for this session because direct camera rendering is unavailable "
                        f"({head_view_preflight_error}).",
                        flush=True,
                    )
                else:
                    try:
                        candidate_head_view_xr_display = HeadViewXrDisplayBridge(
                            config=head_view_xr_display_config,
                            camera_prim_path=head_view_camera.camera_path,
                            required_xr_extensions=candidate_teleop.required_xr_extensions,
                            sim_device=str(args.device),
                        )
                        candidate_teleop.set_oxr_handles(
                            candidate_head_view_xr_display.oxr_handles
                        )
                        if (
                            not head_view_xr_display_config.activate_on_calibration
                            or not avp_frame_binding_config.enabled
                        ):
                            candidate_head_view_xr_display.set_visible(True)
                    except Exception as exc:
                        if candidate_head_view_xr_display is not None:
                            try:
                                candidate_head_view_xr_display.close()
                            except Exception:
                                pass
                            candidate_head_view_xr_display = None
                        if _is_xr_runtime_unavailable_error(exc):
                            raise
                        candidate_teleop.set_oxr_handles(None)
                        print(
                            f"[{status_label}] warning: disabling AVP head-view XR display "
                            f"for this session because startup failed "
                            f"({_format_exception_chain(exc)}).",
                            flush=True,
                        )
            candidate_teleop.__enter__()
        except Exception as exc:
            try:
                candidate_teleop.__exit__(None, None, None)
            except Exception:
                pass
            if candidate_head_view_xr_display is not None:
                try:
                    candidate_head_view_xr_display.close()
                except Exception:
                    pass
            if _is_xr_runtime_unavailable_error(exc):
                enter_xr_waiting_state(exc, phase="startup")
                return False
            raise

        teleop = candidate_teleop
        teleop_started = True
        head_view_xr_display = candidate_head_view_xr_display
        next_xr_retry_time = 0.0
        xr_waiting_announced = False
        if head_view_xr_display is not None:
            print(
                f"[{status_label}] AVP head-view XR display enabled: "
                f"resolution={head_view_xr_display_config.resolution_px[0]}x"
                f"{head_view_xr_display_config.resolution_px[1]}, "
                f"lock_mode={head_view_xr_display_config.lock_mode}, "
                f"activate_on_calibration={head_view_xr_display_config.activate_on_calibration}.",
                flush=True,
            )
        print(
            f"[{status_label}] OpenXR teleop session started"
            f"{' after HMD/runtime reconnect' if was_waiting else ''}.",
            flush=True,
        )
        return True

    start_time = time.monotonic()
    try:
        if not simulation_app.is_running():
            has_keyboard = bool(
                app_window is not None and app_window.get_keyboard() is not None
            )
            print(
                f"[{status_label}] simulation app is not running at teleop loop start; "
                "exiting before the first teleop frame. "
                f"headless={getattr(args, 'headless', None)} "
                f"app_window={app_window is not None} "
                f"keyboard={has_keyboard}",
                flush=True,
            )
        while simulation_app.is_running():
            if (
                args.duration_s > 0.0
                and time.monotonic() - start_time >= args.duration_s
            ):
                break

            start_button_rising = keyboard_start_requested
            keyboard_start_requested = False
            reset_button_rising = keyboard_reset_requested
            keyboard_reset_requested = False

            if reset_button_rising:
                teleop_armed = False
                start_waiting_announced = False
                marker_target_poses = {}
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
                should_retry = (
                    start_button_rising or time.monotonic() >= next_xr_retry_time
                )
                if should_retry:
                    try_start_openxr_runtime()
                if teleop is None:
                    hold_robot_targets()
                    step_scene_once()
                    continue

            try:
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
                        marker_target_poses = {}
                        hold_robot_targets()
                        step_scene_once(
                            target_poses=sample_target_poses(
                                sample,
                                resolve_marker_pose=marker_pose_resolver,
                            ),
                            update_ee_frames=arm_ik is not None,
                        )
                        continue

                if use_native_hand_targets:
                    raw_left_targets = ordered_hand_targets(
                        sample,
                        "left",
                        wuji_hand_config.left_joint_names,
                    )
                    raw_right_targets = ordered_hand_targets(
                        sample,
                        "right",
                        wuji_hand_config.right_joint_names,
                    )
                else:
                    raw_left_targets, raw_right_targets = wuji_backend.targets(sample)

                left_targets = left_postprocessor.process(raw_left_targets)
                right_targets = right_postprocessor.process(raw_right_targets)

                if left_targets is not None:
                    robot.set_joint_position_target_index(
                        target=torch.as_tensor(
                            left_targets, device=sim.device
                        ).unsqueeze(0),
                        joint_ids=left_joint_ids,
                    )
                if right_targets is not None:
                    robot.set_joint_position_target_index(
                        target=torch.as_tensor(
                            right_targets, device=sim.device
                        ).unsqueeze(0),
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
                        head_view_camera.activate()
                    if (
                        auxiliary_viewport_config.enabled
                        and auxiliary_viewport_config.activate_on_calibration
                        and avp_frame_binding.calibrated
                    ):
                        auxiliary_viewport.show()
                    if (
                        head_view_xr_display is not None
                        and head_view_xr_display_config.activate_on_calibration
                        and avp_frame_binding.calibrated
                    ):
                        head_view_xr_display.set_visible(True)
                if whole_body_yaw is not None:
                    whole_body_yaw.update(avp_frame_binding)
                if arm_ik is not None:
                    arm_ik.update(sample)
                    marker_target_poses = arm_ik.target_pose_world_np()
                else:
                    marker_target_poses = {}

                step_scene_once(
                    target_poses=sample_target_poses(
                        sample,
                        resolve_marker_pose=marker_pose_resolver,
                    ),
                    update_ee_frames=arm_ik is not None,
                )
            except Exception as exc:
                if not _is_xr_runtime_unavailable_error(exc):
                    raise
                enter_xr_waiting_state(exc, phase="runtime")
    except Exception as exc:
        print(
            f"[{status_label}] fatal runtime error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        raise
    finally:
        try:
            if keyboard_subscription is not None:
                unsubscribe_fn = getattr(
                    input_interface, "unsubscribe_from_keyboard_events", None
                )
                if callable(unsubscribe_fn) and app_window is not None:
                    unsubscribe_fn(
                        app_window.get_keyboard(),
                        keyboard_subscription,
                    )
            close_openxr_runtime()
        finally:
            simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
