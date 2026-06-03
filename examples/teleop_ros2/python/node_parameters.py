# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ROS parameter declaration, resolution, and validation for teleop_ros2_node.

Calling any ``_load_*`` helper has the side effect of registering its ROS
parameter on the supplied ``Node`` via ``Node.declare_parameter``. Helpers
declare each parameter at most once, read it back, validate it, optionally log
a startup message, and return the resolved value(s). The public entry point
``create_node_parameters`` orchestrates the helpers in dependency order and
assembles a frozen ``NodeParameters`` snapshot.
"""

import itertools
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.node import Node
from rclpy.parameter import Parameter
from scipy.spatial.transform import Rotation

from isaacteleop.deviceio import McapReplayConfig
from isaacteleop.retargeting_engine.deviceio_source_nodes.pedals_source import (
    DEFAULT_PEDAL_COLLECTION_ID,
)
from isaacteleop.teleop_session_manager import SessionMode

from constants import (
    HAND_RETARGETERS,
    TELEOP_MODES,
    HandRetargeter,
    resolve_hand_retargeter,
    uses_hands_source_for_controller,
)


@dataclass(frozen=True)
class NodeParameters:
    """Resolved snapshot of every ROS parameter consumed by TeleopRos2Node."""

    mode: str
    sleep_period_s: float
    hand_retargeter: HandRetargeter
    resolved_hand_retargeter: HandRetargeter
    controller_uses_hands_source: bool
    config_asset_root: Path
    session_mode: SessionMode
    mcap_config: McapReplayConfig | None
    cloudxr_install_dir: str
    cloudxr_env_config: str | None
    cloudxr_accept_eula: bool
    pedal_collection_id: str
    world_frame: str
    right_wrist_frame: str
    left_wrist_frame: str
    head_frame: str
    transform_translation: list[float] | None
    transform_rotation: Rotation | None
    left_finger_joint_name_aliases: list[str] | None
    right_finger_joint_name_aliases: list[str] | None


def _load_cloudxr(node: Node) -> tuple[str, str | None, bool]:
    node.declare_parameter(
        "cloudxr_install_dir",
        "~/.cloudxr",
        ParameterDescriptor(
            type=ParameterType.PARAMETER_STRING,
            description=(
                "CloudXR install directory used by the in-process "
                "CloudXRLauncher (runtime + WSS proxy). Defaults to ~/.cloudxr."
            ),
        ),
    )
    node.declare_parameter(
        "cloudxr_env_config",
        "",
        ParameterDescriptor(
            type=ParameterType.PARAMETER_STRING,
            description=(
                "Optional CloudXR env file (KEY=value per line) passed to "
                "CloudXRLauncher to override default CloudXR env vars. Empty "
                "uses the built-in defaults."
            ),
        ),
    )
    node.declare_parameter(
        "cloudxr_accept_eula",
        False,
        ParameterDescriptor(
            type=ParameterType.PARAMETER_BOOL,
            description=(
                "Accept the NVIDIA CloudXR EULA non-interactively. Required for "
                "container/non-interactive runs; otherwise the launcher prompts "
                "on stdin the first time."
            ),
        ),
    )

    install_dir = (
        node.get_parameter("cloudxr_install_dir")
        .get_parameter_value()
        .string_value.strip()
    ) or "~/.cloudxr"

    env_config_str = (
        node.get_parameter("cloudxr_env_config")
        .get_parameter_value()
        .string_value.strip()
    )
    env_config: str | None = None
    if env_config_str:
        env_config_path = Path(env_config_str).expanduser()
        if not env_config_path.is_file():
            raise FileNotFoundError(
                f"cloudxr_env_config file not found: {env_config_path}"
            )
        env_config = str(env_config_path)

    accept_eula = (
        node.get_parameter("cloudxr_accept_eula").get_parameter_value().bool_value
    )
    return install_dir, env_config, accept_eula


def _load_config_asset_root(node: Node) -> Path:
    node.declare_parameter(
        "config_asset_root",
        "",
        ParameterDescriptor(
            type=ParameterType.PARAMETER_STRING,
            description=(
                "Directory containing teleop_ros2 configs/ and assets/. "
                "Leave empty to use the installed or source example root."
            ),
        ),
    )
    config_asset_root_str = (
        node.get_parameter("config_asset_root")
        .get_parameter_value()
        .string_value.strip()
    )
    if config_asset_root_str:
        config_asset_root = Path(config_asset_root_str).expanduser().resolve()
        if not config_asset_root.is_dir():
            raise FileNotFoundError(
                f"config_asset_root directory not found: {config_asset_root}"
            )
    else:
        config_asset_root = Path(__file__).resolve().parents[1]
    node.get_logger().info(f"Config/asset root: {config_asset_root}")
    return config_asset_root


def _load_finger_joint_name_aliases(node: Node, side: str) -> list[str] | None:
    # A bare [] default is inferred by rclpy as BYTE_ARRAY on Humble. Declare
    # by type first, then initialize the unset default to [] explicitly.
    param_name = f"{side}_finger_joint_names"
    param = node.declare_parameter(
        param_name,
        Parameter.Type.STRING_ARRAY,
        ParameterDescriptor(
            type=ParameterType.PARAMETER_STRING_ARRAY,
            description=(
                f"Optional {side}-hand joint names for xr_teleop/finger_joints. "
                "Empty means the selected mode's default names."
            ),
            additional_constraints=(
                "Leave empty to use the selected mode's default joint names. "
                "In modes that publish xr_teleop/finger_joints, provide ROS "
                "JointState name aliases matching the selected retargeter output count."
            ),
        ),
    )
    if param.type_ == Parameter.Type.NOT_SET:
        node.set_parameters([Parameter(param_name, Parameter.Type.STRING_ARRAY, [])])

    names = node.get_parameter(param_name).value
    for index, joint_name in enumerate(names, start=1):
        if not joint_name.strip():
            raise ValueError(
                f"Parameter '{param_name}' entry {index} must be a non-empty string"
            )
    return names or None


def _load_frames(node: Node) -> tuple[str, str, str, str]:
    node.declare_parameter(
        "world_frame",
        "world",
        ParameterDescriptor(
            description=(
                "World frame used as the header frame_id for all published messages "
                "and as the parent frame for wrist TF transforms. Defaults to 'world'."
            )
        ),
    )
    node.declare_parameter(
        "right_wrist_frame",
        "right_wrist",
        ParameterDescriptor(description="TF child frame name for the right wrist."),
    )
    node.declare_parameter(
        "left_wrist_frame",
        "left_wrist",
        ParameterDescriptor(description="TF child frame name for the left wrist."),
    )
    node.declare_parameter(
        "head_frame",
        "head",
        ParameterDescriptor(description="TF child frame name for the head."),
    )

    # Every frame must be non-empty and distinct from the others: they become
    # TF frame names that all share the same world parent, so any collision
    # would publish ambiguous transforms.
    frame_names = ("world_frame", "right_wrist_frame", "left_wrist_frame", "head_frame")
    frames = {
        name: node.get_parameter(name).get_parameter_value().string_value
        for name in frame_names
    }
    for name, value in frames.items():
        if not value:
            raise ValueError(f"Parameter '{name}' must not be empty")
    for (name_a, value_a), (name_b, value_b) in itertools.combinations(
        frames.items(), 2
    ):
        if value_a == value_b:
            raise ValueError(
                f"Parameters '{name_a}' and '{name_b}' must be different, got {value_a!r}"
            )
    return tuple(frames.values())


def _load_hand_retargeter(
    node: Node, mode: str
) -> tuple[HandRetargeter, HandRetargeter, bool]:
    node.declare_parameter(
        "hand_retargeter",
        HandRetargeter.MODE_DEFAULT.value,
        ParameterDescriptor(
            description=(
                "Hand retargeter backend. 'mode_default' resolves to "
                "'trihand' in controller_teleop and 'dexpilot' in "
                "hand_teleop. Valid values: 'mode_default', 'trihand', "
                "'pink_ik', or 'dexpilot'."
            )
        ),
    )
    raw_hand_retargeter = (
        node.get_parameter("hand_retargeter").get_parameter_value().string_value
    )
    try:
        hand_retargeter = HandRetargeter(raw_hand_retargeter)
    except ValueError as exc:
        raise ValueError(
            f"Parameter 'hand_retargeter' must be one of {HAND_RETARGETERS}, "
            f"got {raw_hand_retargeter!r}"
        ) from exc
    resolved_hand_retargeter = resolve_hand_retargeter(mode, hand_retargeter)
    controller_uses_hands_source = uses_hands_source_for_controller(
        mode, resolved_hand_retargeter
    )
    if mode in ("hand_teleop", "controller_teleop"):
        node.get_logger().info(f"Hand retargeter: {resolved_hand_retargeter}")
    if controller_uses_hands_source:
        node.get_logger().info(
            "Applying MANUS controller-to-hand transform after pose transform."
        )
    return hand_retargeter, resolved_hand_retargeter, controller_uses_hands_source


def _load_mcap_replay(
    node: Node,
) -> tuple[SessionMode, McapReplayConfig | None]:
    node.declare_parameter(
        "mcap_replay_path",
        "",
        ParameterDescriptor(
            type=ParameterType.PARAMETER_STRING,
            description=(
                "Optional MCAP file to replay through TeleopSession instead "
                "of connecting to live OpenXR/DeviceIO inputs."
            ),
        ),
    )
    mcap_replay_path = (
        node.get_parameter("mcap_replay_path")
        .get_parameter_value()
        .string_value.strip()
    )
    if not mcap_replay_path:
        return SessionMode.LIVE, None

    replay_path = Path(mcap_replay_path).expanduser().resolve()
    if not replay_path.is_file():
        raise FileNotFoundError(f"mcap_replay_path file not found: {replay_path}")
    node.get_logger().info(f"Replaying MCAP input: {replay_path}")
    return SessionMode.REPLAY, McapReplayConfig(str(replay_path))


def _load_mode(node: Node) -> str:
    node.declare_parameter("mode", "controller_teleop")
    mode = node.get_parameter("mode").get_parameter_value().string_value
    if mode not in TELEOP_MODES:
        raise ValueError(
            f"Parameter 'mode' must be one of {TELEOP_MODES}, got {mode!r}"
        )
    node.get_logger().info(f"Mode: {mode}")
    return mode


def _load_pedal_collection_id(node: Node) -> str:
    node.declare_parameter(
        "pedal_collection_id",
        DEFAULT_PEDAL_COLLECTION_ID,
        ParameterDescriptor(
            description=(
                "Tensor collection ID used for hand_teleop foot pedal locomotion. "
                "Must match the pedal pusher or reader collection_id."
            )
        ),
    )
    pedal_collection_id = (
        node.get_parameter("pedal_collection_id").get_parameter_value().string_value
    )
    if not pedal_collection_id:
        raise ValueError("Parameter 'pedal_collection_id' must not be empty")
    return pedal_collection_id


def _load_rate_hz(node: Node) -> float:
    node.declare_parameter("rate_hz", 60.0)
    rate_hz = node.get_parameter("rate_hz").get_parameter_value().double_value
    if rate_hz <= 0 or not math.isfinite(rate_hz):
        raise ValueError("Parameter 'rate_hz' must be > 0")
    return rate_hz


def _load_transform_rotation(node: Node) -> Rotation | None:
    node.declare_parameter(
        "transform_rotation",
        [0.0, 0.0, 0.0, 1.0],
        ParameterDescriptor(
            description=(
                "Optional rotation [qx, qy, qz, qw] used to rotate "
                "published hand/EE pose positions into the ROS world "
                "frame and re-express their orientations in that rotated "
                "basis."
            )
        ),
    )
    transform_rot_arr = (
        node.get_parameter("transform_rotation")
        .get_parameter_value()
        .double_array_value
    )
    if not transform_rot_arr:
        return None
    if len(transform_rot_arr) != 4:
        raise ValueError(
            "Parameter 'transform_rotation' must have 4 elements if provided"
        )
    if np.allclose(transform_rot_arr, [0.0, 0.0, 0.0, 1.0]):
        return None

    transform_rot_floats = [float(x) for x in transform_rot_arr]
    q_norm = np.linalg.norm(transform_rot_floats)
    if q_norm < 1e-6:
        raise ValueError(
            "Parameter 'transform_rotation' must be a valid non-zero quaternion"
        )
    if not math.isclose(q_norm, 1.0, rel_tol=1e-3):
        node.get_logger().warn(
            f"Parameter 'transform_rotation' is not a unit quaternion (norm={q_norm}). Normalizing it."
        )
    normalized_q = np.array(transform_rot_floats) / q_norm
    return Rotation.from_quat(normalized_q)


def _load_transform_translation(node: Node) -> list[float] | None:
    node.declare_parameter(
        "transform_translation",
        [0.0, 0.0, 0.0],
        ParameterDescriptor(
            description=(
                "Optional translation [x, y, z] applied to published "
                "hand/EE pose positions after rotating them into the ROS "
                "world frame."
            )
        ),
    )
    transform_trans_arr = (
        node.get_parameter("transform_translation")
        .get_parameter_value()
        .double_array_value
    )
    if not transform_trans_arr:
        return None
    if len(transform_trans_arr) != 3:
        raise ValueError(
            "Parameter 'transform_translation' must have 3 elements if provided"
        )
    if np.allclose(transform_trans_arr, [0.0, 0.0, 0.0]):
        return None
    return [float(x) for x in transform_trans_arr]


def create_node_parameters(node: Node) -> NodeParameters:
    """Declare every ROS parameter on ``node``, validate, and return the snapshot."""
    rate_hz = _load_rate_hz(node)
    mode = _load_mode(node)
    (
        hand_retargeter,
        resolved_hand_retargeter,
        controller_uses_hands_source,
    ) = _load_hand_retargeter(node, mode)
    config_asset_root = _load_config_asset_root(node)
    session_mode, mcap_config = _load_mcap_replay(node)
    cloudxr_install_dir, cloudxr_env_config, cloudxr_accept_eula = _load_cloudxr(node)
    pedal_collection_id = _load_pedal_collection_id(node)
    world_frame, right_wrist_frame, left_wrist_frame, head_frame = _load_frames(node)
    transform_translation = _load_transform_translation(node)
    transform_rotation = _load_transform_rotation(node)
    left_finger_joint_name_aliases = _load_finger_joint_name_aliases(node, "left")
    right_finger_joint_name_aliases = _load_finger_joint_name_aliases(node, "right")

    return NodeParameters(
        mode=mode,
        sleep_period_s=1.0 / rate_hz,
        hand_retargeter=hand_retargeter,
        resolved_hand_retargeter=resolved_hand_retargeter,
        controller_uses_hands_source=controller_uses_hands_source,
        config_asset_root=config_asset_root,
        session_mode=session_mode,
        mcap_config=mcap_config,
        cloudxr_install_dir=cloudxr_install_dir,
        cloudxr_env_config=cloudxr_env_config,
        cloudxr_accept_eula=cloudxr_accept_eula,
        pedal_collection_id=pedal_collection_id,
        world_frame=world_frame,
        right_wrist_frame=right_wrist_frame,
        left_wrist_frame=left_wrist_frame,
        head_frame=head_frame,
        transform_translation=transform_translation,
        transform_rotation=transform_rotation,
        left_finger_joint_name_aliases=left_finger_joint_name_aliases,
        right_finger_joint_name_aliases=right_finger_joint_name_aliases,
    )
