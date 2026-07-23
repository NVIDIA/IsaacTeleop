# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OpenXR + MANUS input stream for the G1-Wuji teleop example."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import default_config_path, load_yaml_file
from .transforms import transform_controller_pose_to_palm


SIDE_NAMES = ("left", "right")


@dataclass(frozen=True)
class RuntimeDeps:
    DeviceIOSession: Any
    ControllersSource: Any
    HeadSource: Any
    HandsSource: Any
    OutputCombiner: Any
    PluginConfig: Any
    TeleopSession: Any
    TeleopSessionConfig: Any
    ControllerInputIndex: Any
    HandInputIndex: Any
    HandJointIndex: Any
    HeadPoseIndex: Any


@dataclass(frozen=True)
class ControllerPalmOffset:
    pos: tuple[float, float, float]
    quat_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True)
class EePoseConfig:
    source: str
    controller_pose_source: str
    hand_joint: str
    controller_to_palm: dict[str, ControllerPalmOffset]


def _load_runtime_deps() -> RuntimeDeps:
    try:
        import isaacteleop.deviceio as deviceio
        from isaacteleop.retargeting_engine.deviceio_source_nodes import (
            ControllersSource,
            HandsSource,
            HeadSource,
        )
        from isaacteleop.retargeting_engine.interface import OutputCombiner
        from isaacteleop.retargeting_engine.tensor_types.indices import (
            ControllerInputIndex,
            HandInputIndex,
            HandJointIndex,
            HeadPoseIndex,
        )
        from isaacteleop.teleop_session_manager import (
            PluginConfig,
            TeleopSession,
            TeleopSessionConfig,
        )
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"Missing Python dependency {exc.name!r}. Activate an IsaacTeleop "
            "environment with CloudXR and retargeter dependencies."
        ) from exc

    return RuntimeDeps(
        DeviceIOSession=deviceio.DeviceIOSession,
        ControllersSource=ControllersSource,
        HeadSource=HeadSource,
        HandsSource=HandsSource,
        OutputCombiner=OutputCombiner,
        PluginConfig=PluginConfig,
        TeleopSession=TeleopSession,
        TeleopSessionConfig=TeleopSessionConfig,
        ControllerInputIndex=ControllerInputIndex,
        HandInputIndex=HandInputIndex,
        HandJointIndex=HandJointIndex,
        HeadPoseIndex=HeadPoseIndex,
    )


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Config field {name!r} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"Config field {name!r} must be a sequence")
    return value


def _float_tuple(value: Any, *, name: str, length: int) -> tuple[float, ...]:
    raw = _as_sequence(value, name)
    if len(raw) != length:
        raise ValueError(f"Config field {name!r} must contain {length} values")
    return tuple(float(item) for item in raw)


def _resolve_path(path_value: Any, *, base_dir: Path, name: str) -> Path:
    if path_value is None:
        raise ValueError(f"Config field {name!r} is required")
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _load_controller_palm_offsets(
    avp_cfg: Mapping[str, Any],
) -> dict[str, ControllerPalmOffset]:
    offsets: dict[str, ControllerPalmOffset] = {}
    for side in SIDE_NAMES:
        offsets[side] = ControllerPalmOffset(
            pos=_float_tuple(
                avp_cfg.get(f"{side}_controller_to_palm_pos"),
                name=f"avp.{side}_controller_to_palm_pos",
                length=3,
            ),
            quat_xyzw=_float_tuple(
                avp_cfg.get(f"{side}_controller_to_palm_quat_xyzw"),
                name=f"avp.{side}_controller_to_palm_quat_xyzw",
                length=4,
            ),
        )
    return offsets


def _load_ee_pose_config(config: Mapping[str, Any]) -> EePoseConfig:
    avp_cfg = _as_mapping(config.get("avp"), "avp")
    source = str(avp_cfg.get("ee_pose_source", "hand_tracking")).lower()
    hand_joint = str(avp_cfg.get("ee_hand_joint", "wrist")).lower()
    controller_pose_source = str(avp_cfg.get("controller_pose_source", "grip")).lower()

    if source not in {"controller", "hand_tracking"}:
        raise ValueError("avp.ee_pose_source must be 'controller' or 'hand_tracking'")
    if hand_joint not in {"wrist", "palm"}:
        raise ValueError("avp.ee_hand_joint must be 'wrist' or 'palm'")
    if controller_pose_source not in {"aim", "grip"}:
        raise ValueError("avp.controller_pose_source must be 'aim' or 'grip'")

    return EePoseConfig(
        source=source,
        controller_pose_source=controller_pose_source,
        hand_joint=hand_joint,
        controller_to_palm=(
            _load_controller_palm_offsets(avp_cfg) if source == "controller" else {}
        ),
    )


def _controller_pose(
    group: Any,
    *,
    pose_source: str,
    deps: RuntimeDeps,
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
        raise ValueError(f"Unsupported controller pose source: {pose_source!r}")

    if not bool(group[valid_index]):
        return None

    return {
        "position": [float(value) for value in group[position_index]],
        "orientation_xyzw": [float(value) for value in group[orientation_index]],
    }


def _hand_tracking_pose(
    group: Any,
    *,
    joint_name: str,
    deps: RuntimeDeps,
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


def _controller_scalar(
    group: Any,
    index_enum: Any,
    field_name: str,
) -> float:
    return float(group[getattr(index_enum, field_name)])


def _controller_inputs(group: Any, *, deps: RuntimeDeps) -> dict[str, Any] | None:
    if group.is_none:
        return None
    controller_index = deps.ControllerInputIndex
    return {
        "primary_click": _controller_scalar(group, controller_index, "PRIMARY_CLICK")
        > 0.5,
        "secondary_click": _controller_scalar(
            group, controller_index, "SECONDARY_CLICK"
        )
        > 0.5,
        "thumbstick_click": _controller_scalar(
            group, controller_index, "THUMBSTICK_CLICK"
        )
        > 0.5,
        "menu_click": _controller_scalar(group, controller_index, "MENU_CLICK") > 0.5,
        "thumbstick_x": _controller_scalar(group, controller_index, "THUMBSTICK_X"),
        "thumbstick_y": _controller_scalar(group, controller_index, "THUMBSTICK_Y"),
        "squeeze_value": _controller_scalar(group, controller_index, "SQUEEZE_VALUE"),
        "trigger_value": _controller_scalar(group, controller_index, "TRIGGER_VALUE"),
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
    """Facade returning EE poses and MANUS skeletons from TeleopSession."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        config_dir: Path,
        oxr_handles: Any | None = None,
    ) -> None:
        self._config = config
        self._config_dir = config_dir
        self._deps = _load_runtime_deps()
        self._oxr_handles = oxr_handles
        self._session = None
        self._session_context = None
        self._ee_config = _load_ee_pose_config(config)
        self._manus_plugin_configs = self._build_plugin_configs()
        self._required_xr_extensions: tuple[str, ...] = ()
        self._session_config = self._build_session_config()

    @classmethod
    def from_config_file(
        cls,
        path: str | Path | None = None,
        *,
        oxr_handles: Any | None = None,
    ) -> "TeleopMain":
        config_path = Path(path).expanduser() if path else default_config_path()
        config_path = config_path.resolve()
        return cls(
            load_yaml_file(config_path),
            config_dir=config_path.parent,
            oxr_handles=oxr_handles,
        )

    @property
    def required_xr_extensions(self) -> tuple[str, ...]:
        return tuple(self._required_xr_extensions)

    def set_oxr_handles(self, oxr_handles: Any | None) -> None:
        if self._session is not None or self._session_context is not None:
            raise RuntimeError(
                "TeleopMain.set_oxr_handles() must be called before starting the session"
            )
        self._oxr_handles = oxr_handles
        self._session_config = self._build_session_config()

    def __enter__(self) -> "TeleopMain":
        self._session_context = self._deps.TeleopSession(self._session_config)
        self._session = self._session_context.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._session_context is not None:
            self._session_context.__exit__(exc_type, exc_value, traceback)
        self._session_context = None
        self._session = None

    def step(self) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("TeleopMain must be entered before step()")

        result = self._session.step()
        left_hand = result["openxr_hand_left"]
        right_hand = result["openxr_hand_right"]
        controller_outputs = self._controller_outputs(result)
        return {
            "timestamp_s": time.time(),
            "frame_count": self._session.frame_count,
            "head_pose": _head_pose(result["avp_head"], deps=self._deps),
            "ee_poses": {
                "left": self._ee_pose(result, "left"),
                "right": self._ee_pose(result, "right"),
            },
            "hand_active": {
                "left": not left_hand.is_none,
                "right": not right_hand.is_none,
            },
            "hand_skeletons": {
                "left": _hand_tracking_skeleton(left_hand, deps=self._deps),
                "right": _hand_tracking_skeleton(right_hand, deps=self._deps),
            },
            "hand_joint_names": {side: [] for side in SIDE_NAMES},
            "hand_joint_positions": {side: None for side in SIDE_NAMES},
            "controller_inputs": controller_outputs,
        }

    def _build_session_config(self):
        deps = self._deps
        head = deps.HeadSource(name="avp_head")
        hands = deps.HandsSource(name="manus_hands")
        trackers = [head.get_tracker(), hands.get_tracker()]
        output_mapping = {
            "avp_head": head.output("head"),
            "openxr_hand_left": hands.output(deps.HandsSource.LEFT),
            "openxr_hand_right": hands.output(deps.HandsSource.RIGHT),
        }

        if self._ee_config.source == "controller":
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
        return deps.TeleopSessionConfig(
            app_name=str(session_cfg.get("app_name", "G1WujiTeleop")),
            pipeline=pipeline,
            plugins=self._manus_plugin_configs,
            oxr_handles=self._oxr_handles,
        )

    def _build_plugin_configs(self) -> list[Any]:
        plugin_cfg = _as_mapping(self._config.get("manus_plugin"), "manus_plugin")
        if not bool(plugin_cfg.get("enabled", True)):
            return []

        search_paths_raw = _as_sequence(
            plugin_cfg.get("search_paths"), "manus_plugin.search_paths"
        )
        search_paths = [
            _resolve_path(
                path, base_dir=self._config_dir, name="manus_plugin.search_paths"
            )
            for path in search_paths_raw
        ]
        missing = [path for path in search_paths if not path.is_dir()]
        if missing:
            raise FileNotFoundError(
                "MANUS plugin search path does not exist: "
                + ", ".join(str(path) for path in missing)
            )

        return [
            self._deps.PluginConfig(
                plugin_name=str(plugin_cfg.get("plugin_name", "manus_hand_plugin")),
                plugin_root_id=str(plugin_cfg.get("plugin_root_id", "manus")),
                search_paths=search_paths,
                enabled=True,
                plugin_args=[
                    str(arg)
                    for arg in _as_sequence(
                        plugin_cfg.get("args", []), "manus_plugin.args"
                    )
                ],
            )
        ]

    def _controller_outputs(self, result: Mapping[str, Any]) -> dict[str, Any]:
        if self._ee_config.source != "controller":
            return {side: None for side in SIDE_NAMES}
        return {
            side: _controller_inputs(result[f"avp_controller_{side}"], deps=self._deps)
            for side in SIDE_NAMES
        }

    def _ee_pose(self, result: Mapping[str, Any], side: str) -> dict[str, Any] | None:
        if self._ee_config.source == "hand_tracking":
            return _hand_tracking_pose(
                result[f"openxr_hand_{side}"],
                joint_name=self._ee_config.hand_joint,
                deps=self._deps,
            )

        pose = _controller_pose(
            result[f"avp_controller_{side}"],
            pose_source=self._ee_config.controller_pose_source,
            deps=self._deps,
        )
        if pose is None:
            return None
        offset = self._ee_config.controller_to_palm[side]
        palm_pos, palm_quat = transform_controller_pose_to_palm(
            controller_pos=pose["position"],
            controller_quat_xyzw=pose["orientation_xyzw"],
            offset_pos=offset.pos,
            offset_quat_xyzw=offset.quat_xyzw,
        )
        return {
            "position": [float(value) for value in palm_pos],
            "orientation_xyzw": [float(value) for value in palm_quat],
        }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the G1-Wuji input stream.")
    parser.add_argument("--config", default=str(default_config_path()))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    with TeleopMain.from_config_file(args.config) as teleop:
        while True:
            teleop.step()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
