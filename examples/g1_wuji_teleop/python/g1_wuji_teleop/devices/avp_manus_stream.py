# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Non-ROS AVP + MANUS teleop entry point for simulation loops.

The public surface for simulators is ``TeleopMain``:

    with TeleopMain.from_config_file("config/avp_manus.yml") as teleop:
        sample = teleop.step()
        left_ee = sample["ee_poses"]["left"]
        left_skeleton = sample["hand_skeletons"]["left"]
        left_joints = sample["hand_joint_positions"]["left"]

AVP endpoint poses can arrive as OpenXR hand tracking wrist/palm poses or as
controller aim/grip poses. MANUS glove data is expected to arrive as OpenXR hand
tracking, either from an already-running ``manus_hand_plugin`` or from the plugin
managed by ``TeleopSession``.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..paths import default_config_path, ensure_import_paths, repo_root


SIDE_NAMES = ("left", "right")

# Keep the non-ROS G1-Wuji DexPilot path aligned with the official teleop_ros2
# hand-retargeting basis. Using identity here causes OpenXR hand frames to enter
# dex-retargeting in the wrong basis, which looks like joint-level tracking
# errors even when the output names/count match the robot hand.
FIXED_G1_WUJI_RETARGET_TRANSFORM = (
    0.0,
    -1.0,
    0.0,
    -1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    -1.0,
)

FIXED_RETARGET_METHOD = "official_wuji"

FIXED_G1_WUJI_RETARGET_DEFAULTS = {
    "left": {
        "config": Path("local/g1_wuji/hand_left_config.yml"),
        "urdf": Path("../assets/wuji_hand/urdf/left.urdf"),
        "parameter_config_path": "/tmp/avp_manus_left_g1_wuji_dex_params.json",
        "joint_names": [
            "left_finger1_joint1",
            "left_finger1_joint2",
            "left_finger1_joint3",
            "left_finger1_joint4",
            "left_finger2_joint1",
            "left_finger2_joint2",
            "left_finger2_joint3",
            "left_finger2_joint4",
            "left_finger3_joint1",
            "left_finger3_joint2",
            "left_finger3_joint3",
            "left_finger3_joint4",
            "left_finger4_joint1",
            "left_finger4_joint2",
            "left_finger4_joint3",
            "left_finger4_joint4",
            "left_finger5_joint1",
            "left_finger5_joint2",
            "left_finger5_joint3",
            "left_finger5_joint4",
        ],
    },
    "right": {
        "config": Path("local/g1_wuji/hand_right_config.yml"),
        "urdf": Path("../assets/wuji_hand/urdf/right.urdf"),
        "parameter_config_path": "/tmp/avp_manus_right_g1_wuji_dex_params.json",
        "joint_names": [
            "right_finger1_joint1",
            "right_finger1_joint2",
            "right_finger1_joint3",
            "right_finger1_joint4",
            "right_finger2_joint1",
            "right_finger2_joint2",
            "right_finger2_joint3",
            "right_finger2_joint4",
            "right_finger3_joint1",
            "right_finger3_joint2",
            "right_finger3_joint3",
            "right_finger3_joint4",
            "right_finger4_joint1",
            "right_finger4_joint2",
            "right_finger4_joint3",
            "right_finger4_joint4",
            "right_finger5_joint1",
            "right_finger5_joint2",
            "right_finger5_joint3",
            "right_finger5_joint4",
        ],
    },
}

FIXED_NATIVE_RETARGET_DEFAULTS_BY_VARIANT = {"g1_wuji": FIXED_G1_WUJI_RETARGET_DEFAULTS}


@dataclass(frozen=True)
class RuntimeDeps:
    DeviceIOSession: Any
    ControllersSource: Any
    DexHandRetargeter: Any
    DexHandRetargeterConfig: Any
    HeadSource: Any
    HandsSource: Any
    OpenXRSessionHandles: Any
    OutputCombiner: Any
    PluginConfig: Any
    TeleopSession: Any
    TeleopSessionConfig: Any
    ControllerInputIndex: Any
    HandInputIndex: Any
    HandJointIndex: Any
    HeadPoseIndex: Any


def _default_config_path() -> Path:
    return default_config_path()


def _repo_root() -> Path:
    return repo_root()


def _load_runtime_deps() -> RuntimeDeps:
    try:
        import isaacteleop.deviceio as deviceio
        from isaacteleop.retargeting_engine.deviceio_source_nodes import (
            ControllersSource,
            HeadSource,
            HandsSource,
        )
        from isaacteleop.retargeting_engine.interface import OutputCombiner
        from isaacteleop.retargeting_engine.tensor_types.indices import (
            ControllerInputIndex,
            HandInputIndex,
            HandJointIndex,
            HeadPoseIndex,
        )
        from isaacteleop.oxr import OpenXRSessionHandles
        from isaacteleop.retargeters import DexHandRetargeter, DexHandRetargeterConfig
        from isaacteleop.teleop_session_manager import (
            PluginConfig,
            TeleopSession,
            TeleopSessionConfig,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"Missing Python dependency {exc.name!r}. Activate an IsaacTeleop "
            "environment with retargeter dependencies before running the G1-Wuji "
            "teleop AVP/MANUS stream."
        ) from exc

    return RuntimeDeps(
        DeviceIOSession=deviceio.DeviceIOSession,
        ControllersSource=ControllersSource,
        DexHandRetargeter=DexHandRetargeter,
        DexHandRetargeterConfig=DexHandRetargeterConfig,
        HeadSource=HeadSource,
        HandsSource=HandsSource,
        OpenXRSessionHandles=OpenXRSessionHandles,
        OutputCombiner=OutputCombiner,
        PluginConfig=PluginConfig,
        TeleopSession=TeleopSession,
        TeleopSessionConfig=TeleopSessionConfig,
        ControllerInputIndex=ControllerInputIndex,
        HandInputIndex=HandInputIndex,
        HandJointIndex=HandJointIndex,
        HeadPoseIndex=HeadPoseIndex,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyYAML is required to load G1-Wuji teleop config files."
        ) from exc

    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Config field {name!r} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"Config field {name!r} must be a sequence")
    return value


def _robot_variant_from_config(config: Mapping[str, Any]) -> str:
    robot_cfg = _as_mapping(config.get("robot"), "robot")
    raw = str(robot_cfg.get("variant", "g1_wuji")).strip().lower()
    aliases = {
        "g1wuji": "g1_wuji",
        "g1-wuji": "g1_wuji",
        "wuji": "g1_wuji",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in FIXED_NATIVE_RETARGET_DEFAULTS_BY_VARIANT:
        raise ValueError(
            f"Unsupported robot.variant={raw!r}. Expected one of "
            f"{sorted(FIXED_NATIVE_RETARGET_DEFAULTS_BY_VARIANT)}"
        )
    return normalized


def _retarget_method_from_config(config: Mapping[str, Any]) -> str:
    retargeting_cfg = _as_mapping(config.get("retargeting"), "retargeting")
    raw = str(retargeting_cfg.get("method", FIXED_RETARGET_METHOD)).strip().lower()
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
    normalized = aliases.get(raw, raw)
    if normalized not in {"native_dex", "official_wuji"}:
        raise ValueError(
            "Config field 'retargeting.method' must be one of "
            "['native_dex', 'official_wuji']"
        )
    return normalized


def _use_native_hand_targets_from_config(config: Mapping[str, Any]) -> bool:
    return _retarget_method_from_config(config) == "native_dex"


def _resolve_path(path_value: str | None, *, base_dir: Path, default: Path) -> Path:
    path = Path(path_value).expanduser() if path_value else default
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _default_plugin_search_paths() -> list[Path]:
    root = _repo_root()
    return [
        root / "install" / "plugins",
        Path("/opt/isaacteleop/install/plugins"),
    ]


def _tensor_values(group: Any) -> list[float]:
    return [float(group[index]) for index in range(len(group))]


def _controller_pose(
    group: Any, *, pose_source: str, deps: RuntimeDeps
) -> dict[str, Any] | None:
    if group.is_none:
        return None

    if pose_source == "aim":
        position_index = deps.ControllerInputIndex.AIM_POSITION
        orientation_index = deps.ControllerInputIndex.AIM_ORIENTATION
        valid_index = deps.ControllerInputIndex.AIM_IS_VALID
    elif pose_source == "grip":
        position_index = deps.ControllerInputIndex.GRIP_POSITION
        orientation_index = deps.ControllerInputIndex.GRIP_ORIENTATION
        valid_index = deps.ControllerInputIndex.GRIP_IS_VALID
    else:
        raise ValueError(f"ee_pose_source must be 'aim' or 'grip', got {pose_source!r}")

    if not bool(group[valid_index]):
        return None

    return {
        "position": [float(value) for value in group[position_index]],
        "orientation_xyzw": [float(value) for value in group[orientation_index]],
    }


def _hand_tracking_pose(
    group: Any, *, joint_name: str, deps: RuntimeDeps
) -> dict[str, Any] | None:
    if group.is_none:
        return None

    import numpy as np

    joint_index = int(getattr(deps.HandJointIndex, joint_name.upper()))
    valid = np.from_dlpack(group[deps.HandInputIndex.JOINT_VALID])
    if not bool(valid[joint_index]):
        return None

    positions = np.from_dlpack(group[deps.HandInputIndex.JOINT_POSITIONS])
    orientations = np.from_dlpack(group[deps.HandInputIndex.JOINT_ORIENTATIONS])
    return {
        "position": [float(value) for value in positions[joint_index]],
        "orientation_xyzw": [float(value) for value in orientations[joint_index]],
    }


def _head_pose(group: Any, *, deps: RuntimeDeps) -> dict[str, Any] | None:
    if group.is_none or not bool(group[deps.HeadPoseIndex.IS_VALID]):
        return None

    return {
        "position": [float(value) for value in group[deps.HeadPoseIndex.POSITION]],
        "orientation_xyzw": [
            float(value) for value in group[deps.HeadPoseIndex.ORIENTATION]
        ],
    }


def _controller_inputs(group: Any, *, deps: RuntimeDeps) -> dict[str, Any] | None:
    if group.is_none:
        return None
    return {
        "primary_click": bool(group[deps.ControllerInputIndex.PRIMARY_CLICK] > 0.5),
        "secondary_click": bool(group[deps.ControllerInputIndex.SECONDARY_CLICK] > 0.5),
        "thumbstick_click": bool(
            group[deps.ControllerInputIndex.THUMBSTICK_CLICK] > 0.5
        ),
        "menu_click": bool(group[deps.ControllerInputIndex.MENU_CLICK] > 0.5),
        "thumbstick_x": float(group[deps.ControllerInputIndex.THUMBSTICK_X]),
        "thumbstick_y": float(group[deps.ControllerInputIndex.THUMBSTICK_Y]),
        "squeeze_value": float(group[deps.ControllerInputIndex.SQUEEZE_VALUE]),
        "trigger_value": float(group[deps.ControllerInputIndex.TRIGGER_VALUE]),
    }


def _openxr_hand_joint_names(deps: RuntimeDeps) -> list[str]:
    return [
        name.lower()
        for name, _index in sorted(
            deps.HandJointIndex.__members__.items(),
            key=lambda item: int(item[1]),
        )
    ]


def _hand_tracking_skeleton(group: Any, *, deps: RuntimeDeps) -> dict[str, Any] | None:
    if group.is_none:
        return None

    import numpy as np

    positions = np.from_dlpack(group[deps.HandInputIndex.JOINT_POSITIONS]).copy()
    valid = np.from_dlpack(group[deps.HandInputIndex.JOINT_VALID]).astype(bool).copy()
    if positions.ndim != 2 or positions.shape[1] != 3:
        return None
    if valid.ndim != 1 or positions.shape[0] != valid.shape[0]:
        return None

    return {
        "joint_names": _openxr_hand_joint_names(deps),
        "positions": [[float(coord) for coord in position] for position in positions],
        "valid": [bool(value) for value in valid],
    }


class TeleopMain:
    """Small non-ROS facade returning AVP EE poses and MANUS retargeted joints."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: Path,
        oxr_handles: Any | None = None,
    ) -> None:
        ensure_import_paths()
        self._config = config
        self._config_dir = config_dir
        self._deps = _load_runtime_deps()
        self._use_native_hand_targets = _use_native_hand_targets_from_config(config)
        self._oxr_handles = oxr_handles
        self._session = None
        self._session_context = None
        (
            self._ee_pose_source,
            self._controller_pose_source,
            self._ee_hand_joint,
            self._controller_fallback_enabled,
        ) = self._load_ee_pose_config()
        self._manus_plugin_required = self._load_manus_plugin_required()
        self._manus_plugin_configs = self._build_plugin_configs()
        self._manus_plugin_disabled_for_session = False
        self._ee_source_announced: set[tuple[str, str]] = set()
        self._hand_joint_names: dict[str, list[str]] = {}
        self._required_xr_extensions: tuple[str, ...] = ()
        self._session_config_includes_plugins = True
        self._session_config = self._build_session_config(include_plugins=True)

    @classmethod
    def from_config_file(
        cls,
        path: str | Path | None = None,
        *,
        oxr_handles: Any | None = None,
    ) -> "TeleopMain":
        config_path = Path(path).expanduser() if path else _default_config_path()
        config_path = config_path.resolve()
        config = _load_yaml(config_path)
        return cls(config, config_dir=config_path.parent, oxr_handles=oxr_handles)

    @property
    def hand_joint_names(self) -> dict[str, list[str]]:
        return {side: list(names) for side, names in self._hand_joint_names.items()}

    @property
    def required_xr_extensions(self) -> tuple[str, ...]:
        return tuple(self._required_xr_extensions)

    def set_oxr_handles(self, oxr_handles: Any | None) -> None:
        if self._session is not None or self._session_context is not None:
            raise RuntimeError(
                "TeleopMain.set_oxr_handles() must be called before starting the session"
            )
        self._oxr_handles = oxr_handles
        self._session_config_includes_plugins = True
        self._session_config = self._build_session_config(include_plugins=True)

    def __enter__(self) -> "TeleopMain":
        try:
            self._start_session(include_plugins=True)
        except Exception as exc:
            can_restart = self._can_restart_without_manus_plugin(startup=True)
            self._close_session()
            if not can_restart:
                raise
            self._disable_optional_manus_plugin(exc, phase="startup")
            self._start_session(include_plugins=False)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._session_context is not None:
            self._session_context.__exit__(exc_type, exc_value, traceback)
        self._session_context = None
        self._session = None

    def _start_session(self, *, include_plugins: bool) -> None:
        if include_plugins != self._session_config_includes_plugins:
            self._session_config = self._build_session_config(
                include_plugins=include_plugins
            )
            self._session_config_includes_plugins = include_plugins
        self._session_context = self._deps.TeleopSession(self._session_config)
        self._session = self._session_context.__enter__()

    def _close_session(self) -> None:
        session_context = self._session_context
        if session_context is not None:
            try:
                session_context.__exit__(None, None, None)
            finally:
                exit_stack = getattr(session_context, "_exit_stack", None)
                if exit_stack is not None:
                    exit_stack.close()
        self._session_context = None
        self._session = None

    def _can_restart_without_manus_plugin(self, *, startup: bool) -> bool:
        if (
            self._manus_plugin_required
            or self._manus_plugin_disabled_for_session
            or not self._manus_plugin_configs
        ):
            return False
        if startup:
            return bool(
                getattr(self._session_context, "plugin_managers", ())
                or getattr(self._session_context, "plugin_contexts", ())
            )
        if self._session is None:
            return False
        return bool(getattr(self._session, "plugin_contexts", ()))

    def _disable_optional_manus_plugin(self, exc: Exception, *, phase: str) -> None:
        self._manus_plugin_disabled_for_session = True
        print(
            "[TeleopMain] optional MANUS plugin failed during "
            f"{phase}; restarting without it so AVP/controller EE teleop can continue "
            f"({type(exc).__name__}: {exc}).",
            flush=True,
        )

    def step(self) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError(
                "TeleopMain must be used as a context manager before step()"
            )

        try:
            result = self._session.step()
        except Exception as exc:
            if not self._can_restart_without_manus_plugin(startup=False):
                raise
            self._close_session()
            self._disable_optional_manus_plugin(exc, phase="runtime")
            self._start_session(include_plugins=False)
            result = self._session.step()
        left_hand = result["openxr_hand_left"]
        right_hand = result["openxr_hand_right"]
        hand_active = {
            "left": not left_hand.is_none,
            "right": not right_hand.is_none,
        }
        hand_joint_positions = {"left": None, "right": None}
        if self._use_native_hand_targets:
            if hand_active["left"] and "left_hand_joints" in result:
                hand_joint_positions["left"] = _tensor_values(
                    result["left_hand_joints"]
                )
            if hand_active["right"] and "right_hand_joints" in result:
                hand_joint_positions["right"] = _tensor_values(
                    result["right_hand_joints"]
                )

        return {
            "timestamp_s": time.time(),
            "frame_count": self._session.frame_count,
            "head_pose": _head_pose(result["avp_head"], deps=self._deps),
            "ee_poses": {
                "left": self._ee_pose(result, "left"),
                "right": self._ee_pose(result, "right"),
            },
            "hand_active": hand_active,
            "hand_skeletons": {
                "left": _hand_tracking_skeleton(left_hand, deps=self._deps),
                "right": _hand_tracking_skeleton(right_hand, deps=self._deps),
            },
            "hand_joint_names": self.hand_joint_names,
            "hand_joint_positions": hand_joint_positions,
            "controller_inputs": {
                "left": (
                    _controller_inputs(result["avp_controller_left"], deps=self._deps)
                    if "avp_controller_left" in result
                    else None
                ),
                "right": (
                    _controller_inputs(result["avp_controller_right"], deps=self._deps)
                    if "avp_controller_right" in result
                    else None
                ),
            },
        }

    def _build_session_config(self, *, include_plugins: bool):
        deps = self._deps
        head = deps.HeadSource(name="avp_head")
        hands = deps.HandsSource(name="manus_hands")
        trackers = [head.get_tracker(), hands.get_tracker()]

        output_mapping = {
            "avp_head": head.output("head"),
            "openxr_hand_left": hands.output(deps.HandsSource.LEFT),
            "openxr_hand_right": hands.output(deps.HandsSource.RIGHT),
        }
        if self._use_native_hand_targets:
            left_retargeter, right_retargeter = self._build_hand_retargeters()
            left_connected = left_retargeter.connect(
                {deps.HandsSource.LEFT: hands.output(deps.HandsSource.LEFT)}
            )
            right_connected = right_retargeter.connect(
                {deps.HandsSource.RIGHT: hands.output(deps.HandsSource.RIGHT)}
            )

            left_joint_type = left_connected.output_types()["hand_joints"]
            right_joint_type = right_connected.output_types()["hand_joints"]
            self._hand_joint_names = {
                "left": [tensor_type.name for tensor_type in left_joint_type.types],
                "right": [tensor_type.name for tensor_type in right_joint_type.types],
            }
            output_mapping.update(
                {
                    "left_hand_joints": left_connected.output("hand_joints"),
                    "right_hand_joints": right_connected.output("hand_joints"),
                }
            )
        else:
            # The official Wuji route consumes MANUS/OpenXR skeletons directly in session.py.
            # Do not require native Dex tensors when retargeting.method selects that path.
            self._hand_joint_names = {side: [] for side in SIDE_NAMES}

        if self._ee_pose_source == "controller" or self._controller_fallback_enabled:
            controllers = deps.ControllersSource(name="avp_controllers")
            trackers.append(controllers.get_tracker())
            output_mapping.update(
                {
                    "avp_controller_left": controllers.output(
                        deps.ControllersSource.LEFT
                    ),
                    "avp_controller_right": controllers.output(
                        deps.ControllersSource.RIGHT
                    ),
                }
            )

        pipeline = deps.OutputCombiner(output_mapping)
        self._required_xr_extensions = tuple(
            deps.DeviceIOSession.get_required_extensions(trackers)
        )

        session_cfg = _as_mapping(self._config.get("session"), "session")
        app_name = str(session_cfg.get("app_name", "AvpManusTeleopMain"))
        return deps.TeleopSessionConfig(
            app_name=app_name,
            pipeline=pipeline,
            plugins=self._manus_plugin_configs if include_plugins else [],
            oxr_handles=self._oxr_handles,
        )

    def _build_hand_retargeters(self) -> tuple[Any, Any]:
        deps = self._deps
        retargeting_cfg = _as_mapping(self._config.get("retargeting"), "retargeting")
        robot_variant = _robot_variant_from_config(self._config)
        variant_defaults = FIXED_NATIVE_RETARGET_DEFAULTS_BY_VARIANT[robot_variant]
        transform = tuple(
            float(value)
            for value in _as_sequence(
                retargeting_cfg.get(
                    "handtracking_to_baselink_frame_transform",
                    FIXED_G1_WUJI_RETARGET_TRANSFORM,
                ),
                "retargeting.handtracking_to_baselink_frame_transform",
            )
            or FIXED_G1_WUJI_RETARGET_TRANSFORM
        )
        if len(transform) != 9:
            raise ValueError(
                "retargeting.handtracking_to_baselink_frame_transform must have 9 values"
            )

        side_retargeters = []
        for side in SIDE_NAMES:
            side_cfg = _as_mapping(retargeting_cfg.get(side), f"retargeting.{side}")
            fixed_defaults = variant_defaults[side]
            config_path = _require_file(
                _resolve_path(
                    side_cfg.get("config"),
                    base_dir=self._config_dir,
                    default=fixed_defaults["config"],
                ),
                f"{side} hand retargeting config",
            )
            urdf_path = _require_file(
                _resolve_path(
                    side_cfg.get("urdf"),
                    base_dir=self._config_dir,
                    default=fixed_defaults["urdf"],
                ),
                f"{side} hand URDF",
            )
            joint_names = side_cfg.get("joint_names")
            if joint_names is not None:
                joint_names = [
                    str(name)
                    for name in _as_sequence(
                        joint_names, f"retargeting.{side}.joint_names"
                    )
                ]
            elif "joint_names" in fixed_defaults:
                joint_names = [str(name) for name in fixed_defaults["joint_names"]]
            if joint_names is not None and robot_variant == "g1_wuji":
                # DexHandRetargeter populates output tensors by matching requested output
                # names against the URDF DOF names reported by the optimizer. Wuji's hand
                # URDF uses unprefixed names like finger1_joint1, so strip side prefixes
                # here and let session.py re-add them later when ordering robot targets.
                side_prefix = f"{side}_"
                joint_names = [
                    name[len(side_prefix) :] if name.startswith(side_prefix) else name
                    for name in joint_names
                ]

            retargeter_config = deps.DexHandRetargeterConfig(
                hand_retargeting_config=str(config_path),
                hand_urdf=str(urdf_path),
                hand_joint_names=joint_names,
                handtracking_to_baselink_frame_transform=transform,
                hand_side=side,
                parameter_config_path=side_cfg.get(
                    "parameter_config_path",
                    fixed_defaults["parameter_config_path"],
                ),
            )
            retargeter = deps.DexHandRetargeter(
                retargeter_config, name=f"{side}_manus_dex"
            )
            output_joint_names = list(
                retargeter.output_types()["hand_joints"].types  # type: ignore[index]
            )
            print(
                f"[Manus][DexPilot] variant={robot_variant} side={side} "
                f"config={config_path} urdf={urdf_path} "
                f"transform={transform} "
                f"joint_count={len(output_joint_names)} "
                f"first_joints={[tensor_type.name for tensor_type in output_joint_names[:5]]}",
                flush=True,
            )
            side_retargeters.append(retargeter)

        return side_retargeters[0], side_retargeters[1]

    def _build_plugin_configs(self) -> list[Any]:
        plugin_cfg = _as_mapping(self._config.get("manus_plugin"), "manus_plugin")
        if not bool(plugin_cfg.get("enabled", True)):
            return []

        search_paths_cfg = _as_sequence(
            plugin_cfg.get("search_paths"), "manus_plugin.search_paths"
        )
        if search_paths_cfg:
            search_paths = [
                _resolve_path(str(path), base_dir=self._config_dir, default=Path())
                for path in search_paths_cfg
            ]
        else:
            search_paths = _default_plugin_search_paths()

        return [
            self._deps.PluginConfig(
                plugin_name=str(plugin_cfg.get("plugin_name", "manus_hand_plugin")),
                plugin_root_id=str(plugin_cfg.get("plugin_root_id", "manus")),
                search_paths=search_paths,
                enabled=True,
                plugin_args=[
                    str(arg)
                    for arg in _as_sequence(plugin_cfg.get("args"), "manus_plugin.args")
                ],
            )
        ]

    def _load_manus_plugin_required(self) -> bool:
        plugin_cfg = _as_mapping(self._config.get("manus_plugin"), "manus_plugin")
        return bool(plugin_cfg.get("required", False))

    def _load_ee_pose_config(self) -> tuple[str, str, str, bool]:
        avp_cfg = _as_mapping(self._config.get("avp"), "avp")
        pose_source = str(avp_cfg.get("ee_pose_source", "hand_tracking")).lower()
        controller_pose_source = "aim"
        hand_joint = str(avp_cfg.get("ee_hand_joint", "wrist")).lower()
        controller_fallback_enabled = bool(
            avp_cfg.get("controller_fallback_enabled", True)
        )

        if pose_source in {"aim", "grip"}:
            controller_pose_source = pose_source
            pose_source = "controller"
        elif pose_source in {"controller"}:
            controller_pose_source = str(
                avp_cfg.get("controller_pose_source", "aim")
            ).lower()
        elif pose_source in {"hand_wrist", "wrist"}:
            pose_source = "hand_tracking"
            hand_joint = "wrist"
        elif pose_source in {"hand_palm", "palm"}:
            pose_source = "hand_tracking"
            hand_joint = "palm"

        if pose_source not in {"controller", "hand_tracking"}:
            raise ValueError(
                "avp.ee_pose_source must be one of 'hand_tracking', 'wrist', "
                f"'palm', 'controller', 'aim', or 'grip'; got {pose_source!r}"
            )
        if controller_pose_source not in {"aim", "grip"}:
            raise ValueError(
                "avp.controller_pose_source must be 'aim' or 'grip', got "
                f"{controller_pose_source!r}"
            )
        if hand_joint not in {"wrist", "palm"}:
            raise ValueError(
                f"avp.ee_hand_joint must be 'wrist' or 'palm', got {hand_joint!r}"
            )
        return (
            pose_source,
            controller_pose_source,
            hand_joint,
            controller_fallback_enabled,
        )

    def _ee_pose(self, result: Mapping[str, Any], side: str) -> dict[str, Any] | None:
        if self._ee_pose_source == "controller":
            pose = _controller_pose(
                result[f"avp_controller_{side}"],
                pose_source=self._controller_pose_source,
                deps=self._deps,
            )
            self._announce_ee_source(side, "controller" if pose else "inactive")
            return pose

        # In the AVP optical-hand setup, EE uses OpenXR hand tracking while MANUS
        # only affects finger retargeting; losing MANUS should not disable this path.
        pose = _hand_tracking_pose(
            result[f"openxr_hand_{side}"],
            joint_name=self._ee_hand_joint,
            deps=self._deps,
        )
        if not self._controller_fallback_enabled or not _is_degenerate_pose(pose):
            self._announce_ee_source(side, "hand_tracking" if pose else "inactive")
            return pose

        controller_key = f"avp_controller_{side}"
        if controller_key not in result:
            self._announce_ee_source(side, "inactive")
            return None
        fallback_pose = _controller_pose(
            result[controller_key],
            pose_source=self._controller_pose_source,
            deps=self._deps,
        )
        self._announce_ee_source(
            side,
            "controller_fallback" if fallback_pose else "inactive",
        )
        return fallback_pose

    def _announce_ee_source(self, side: str, source: str) -> None:
        key = (side, source)
        if key in self._ee_source_announced:
            return
        self._ee_source_announced.add(key)
        print(f"[TeleopMain] {side} EE source: {source}", flush=True)


def _is_degenerate_pose(pose: Mapping[str, Any] | None) -> bool:
    # Some injected hand-tracking runtimes report valid wrists at the zero pose
    # before world tracking is available; do not drive IK to that placeholder.
    if pose is None:
        return True
    position = pose.get("position")
    if not isinstance(position, Sequence) or isinstance(position, (str, bytes)):
        return True
    if len(position) != 3:
        return True
    return sum(float(value) * float(value) for value in position) < 1.0e-10


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run non-ROS AVP EE + MANUS dexterous hand teleop."
    )
    parser.add_argument(
        "--config",
        default=str(_default_config_path()),
        help="YAML config for devices, retargeting, and loop settings.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config_path = Path(args.config).expanduser().resolve()
    config = _load_yaml(config_path)

    with TeleopMain(config, config_dir=config_path.parent) as teleop:
        while True:
            teleop.step()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
