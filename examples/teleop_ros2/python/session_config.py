# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopSession graph assembly for teleop_ros2_node."""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from isaacteleop.deviceio import McapReplayConfig
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    Generic3AxisPedalSource,
    HandsSource,
)
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.retargeters import (
    DexHandRetargeter,
    DexHandRetargeterConfig,
    FootPedalRootCmdRetargeter,
    FootPedalRootCmdRetargeterConfig,
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
    TriHandMotionControllerConfig,
    TriHandMotionControllerRetargeter,
)
from isaacteleop.teleop_session_manager import SessionMode, TeleopSessionConfig
from teleop_ros2_retargeters import JointNameAliasRetargeter

from assets import (
    resolve_dex_sharpa_config,
    resolve_dex_sharpa_urdf,
    resolve_sharpa_mjcf,
)
from constants import (
    DEX_HANDTRACKING_TO_BASELINK_FRAME_TRANSFORM,
    HandRetargeter,
    LEFT_FINGER_JOINT_NAMES,
    LEFT_SHARPA_WAVE_JOINT_NAMES,
    RIGHT_FINGER_JOINT_NAMES,
    RIGHT_SHARPA_WAVE_JOINT_NAMES,
    SHARPA_FINGER_JOINT_COUNT,
    SHARPA_HAND_RETARGETERS,
)
from messages import joint_names_from_group_type


@dataclass(frozen=True)
class TeleopRos2SessionConfigContext:
    config_asset_root: Path
    left_finger_joint_name_aliases: Sequence[str] | None
    mcap_config: McapReplayConfig | None
    pedal_collection_id: str
    resolved_hand_retargeter: HandRetargeter
    right_finger_joint_name_aliases: Sequence[str] | None
    session_mode: SessionMode


def build_controller_raw_config(
    context: TeleopRos2SessionConfigContext,
) -> TeleopSessionConfig:
    controllers = ControllersSource(name="controllers")
    pipeline = OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
        }
    )

    return TeleopSessionConfig(
        app_name="TeleopRos2Publisher",
        pipeline=pipeline,
        mode=context.session_mode,
        mcap_config=context.mcap_config,
    )


def build_controller_teleop_config(
    context: TeleopRos2SessionConfigContext,
) -> TeleopSessionConfig:
    controllers = ControllersSource(name="controllers")
    locomotion = LocomotionRootCmdRetargeter(
        LocomotionRootCmdRetargeterConfig(), name="locomotion"
    )
    locomotion_connected = locomotion.connect(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
        }
    )

    pipeline_outputs = {
        "controller_left": controllers.output(ControllersSource.LEFT),
        "controller_right": controllers.output(ControllersSource.RIGHT),
        "root_command": locomotion_connected.output("root_command"),
    }

    if context.resolved_hand_retargeter == HandRetargeter.TRIHAND:
        validate_joint_name_alias_count(
            "left_finger_joint_names",
            context.left_finger_joint_name_aliases,
            len(LEFT_FINGER_JOINT_NAMES),
        )
        validate_joint_name_alias_count(
            "right_finger_joint_names",
            context.right_finger_joint_name_aliases,
            len(RIGHT_FINGER_JOINT_NAMES),
        )
        left_finger_joint_names = (
            list(context.left_finger_joint_name_aliases)
            if context.left_finger_joint_name_aliases is not None
            else list(LEFT_FINGER_JOINT_NAMES)
        )
        right_finger_joint_names = (
            list(context.right_finger_joint_name_aliases)
            if context.right_finger_joint_name_aliases is not None
            else list(RIGHT_FINGER_JOINT_NAMES)
        )

        left_hand_retargeter = TriHandMotionControllerRetargeter(
            TriHandMotionControllerConfig(
                hand_joint_names=left_finger_joint_names, controller_side="left"
            ),
            name="trihand_left",
        )
        right_hand_retargeter = TriHandMotionControllerRetargeter(
            TriHandMotionControllerConfig(
                hand_joint_names=right_finger_joint_names, controller_side="right"
            ),
            name="trihand_right",
        )
        left_hand_connected = left_hand_retargeter.connect(
            {ControllersSource.LEFT: controllers.output(ControllersSource.LEFT)}
        )
        right_hand_connected = right_hand_retargeter.connect(
            {ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT)}
        )
        pipeline_outputs.update(
            {
                "finger_joints_left": left_hand_connected.output("hand_joints"),
                "finger_joints_right": right_hand_connected.output("hand_joints"),
            }
        )
    elif context.resolved_hand_retargeter in SHARPA_HAND_RETARGETERS:
        validate_joint_name_alias_count(
            "left_finger_joint_names",
            context.left_finger_joint_name_aliases,
            SHARPA_FINGER_JOINT_COUNT,
        )
        validate_joint_name_alias_count(
            "right_finger_joint_names",
            context.right_finger_joint_name_aliases,
            SHARPA_FINGER_JOINT_COUNT,
        )
        hands = HandsSource(name="hands")
        left_finger_joints, right_finger_joints = build_sharpa_finger_joint_outputs(
            hands, context, "controller_teleop"
        )
        pipeline_outputs.update(
            {
                "hand_left": hands.output(HandsSource.LEFT),
                "hand_right": hands.output(HandsSource.RIGHT),
                "finger_joints_left": left_finger_joints,
                "finger_joints_right": right_finger_joints,
            }
        )
    else:
        raise ValueError(
            "controller_teleop requires hand_retargeter to resolve to "
            f"'trihand', 'dexpilot', or 'pink_ik', got "
            f"{context.resolved_hand_retargeter!r}"
        )

    pipeline = OutputCombiner(pipeline_outputs)

    return TeleopSessionConfig(
        app_name="TeleopRos2Publisher",
        pipeline=pipeline,
        mode=context.session_mode,
        mcap_config=context.mcap_config,
    )


def build_full_body_config(
    context: TeleopRos2SessionConfigContext,
) -> TeleopSessionConfig:
    controllers = ControllersSource(name="controllers")
    full_body = FullBodySource(name="full_body")
    pipeline = OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
            "full_body": full_body.output(FullBodySource.FULL_BODY),
        }
    )

    return TeleopSessionConfig(
        app_name="TeleopRos2Publisher",
        pipeline=pipeline,
        mode=context.session_mode,
        mcap_config=context.mcap_config,
    )


def build_hand_teleop_config(
    context: TeleopRos2SessionConfigContext,
) -> TeleopSessionConfig:
    validate_joint_name_alias_count(
        "left_finger_joint_names",
        context.left_finger_joint_name_aliases,
        SHARPA_FINGER_JOINT_COUNT,
    )
    validate_joint_name_alias_count(
        "right_finger_joint_names",
        context.right_finger_joint_name_aliases,
        SHARPA_FINGER_JOINT_COUNT,
    )

    hands = HandsSource(name="hands")
    pedals = Generic3AxisPedalSource(
        name="pedals", collection_id=context.pedal_collection_id
    )
    locomotion = FootPedalRootCmdRetargeter(
        FootPedalRootCmdRetargeterConfig(),
        name="foot_pedal",
    )
    locomotion_connected = locomotion.connect({"pedals": pedals.output("pedals")})
    left_finger_joints, right_finger_joints = build_sharpa_finger_joint_outputs(
        hands, context, "hand_teleop"
    )

    pipeline = OutputCombiner(
        {
            "hand_left": hands.output(HandsSource.LEFT),
            "hand_right": hands.output(HandsSource.RIGHT),
            "root_command": locomotion_connected.output("root_command"),
            "finger_joints_left": left_finger_joints,
            "finger_joints_right": right_finger_joints,
        }
    )

    return TeleopSessionConfig(
        app_name="TeleopRos2Publisher",
        pipeline=pipeline,
        mode=context.session_mode,
        mcap_config=context.mcap_config,
    )


def build_session_config(
    mode: str, context: TeleopRos2SessionConfigContext
) -> TeleopSessionConfig:
    if mode == "controller_teleop":
        return build_controller_teleop_config(context)
    if mode == "hand_teleop":
        return build_hand_teleop_config(context)
    if mode == "controller_raw":
        return build_controller_raw_config(context)
    if mode == "full_body":
        return build_full_body_config(context)
    raise ValueError(f"Unsupported mode {mode!r}")


def build_sharpa_finger_joint_outputs(
    hands: HandsSource,
    context: TeleopRos2SessionConfigContext,
    mode_name: str,
):
    if context.resolved_hand_retargeter == HandRetargeter.PINK_IK:
        try:
            from isaacteleop.retargeters import (
                SharpaHandRetargeter,
                SharpaHandRetargeterConfig,
            )
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                f"{mode_name} with hand_retargeter:=pink_ik requires Sharpa "
                "retargeting dependencies. Install/use a build with "
                "isaacteleop[grounding] and bundled robotic_grounding."
            ) from exc

        left_hand_retargeter = SharpaHandRetargeter(
            SharpaHandRetargeterConfig(
                robot_asset_path=resolve_sharpa_mjcf("left_sharpawave_nomesh.xml"),
                hand_side="left",
            ),
            name="sharpa_left",
        )
        right_hand_retargeter = SharpaHandRetargeter(
            SharpaHandRetargeterConfig(
                robot_asset_path=resolve_sharpa_mjcf("right_sharpawave_nomesh.xml"),
                hand_side="right",
            ),
            name="sharpa_right",
        )
        left_alias_name = "sharpa_left_joint_aliases"
        right_alias_name = "sharpa_right_joint_aliases"
    elif context.resolved_hand_retargeter == HandRetargeter.DEXPILOT:
        left_hand_retargeter = DexHandRetargeter(
            DexHandRetargeterConfig(
                hand_retargeting_config=resolve_dex_sharpa_config(
                    context.config_asset_root,
                    "sharpa_wave_left_dexpilot.yml",
                ),
                hand_urdf=resolve_dex_sharpa_urdf(
                    context.config_asset_root,
                    "left_sharpa_wave.urdf",
                ),
                hand_joint_names=LEFT_SHARPA_WAVE_JOINT_NAMES,
                handtracking_to_baselink_frame_transform=(
                    DEX_HANDTRACKING_TO_BASELINK_FRAME_TRANSFORM
                ),
                hand_side="left",
            ),
            name="dex_sharpa_left",
        )
        right_hand_retargeter = DexHandRetargeter(
            DexHandRetargeterConfig(
                hand_retargeting_config=resolve_dex_sharpa_config(
                    context.config_asset_root,
                    "sharpa_wave_right_dexpilot.yml",
                ),
                hand_urdf=resolve_dex_sharpa_urdf(
                    context.config_asset_root,
                    "right_sharpa_wave.urdf",
                ),
                hand_joint_names=RIGHT_SHARPA_WAVE_JOINT_NAMES,
                handtracking_to_baselink_frame_transform=(
                    DEX_HANDTRACKING_TO_BASELINK_FRAME_TRANSFORM
                ),
                hand_side="right",
            ),
            name="dex_sharpa_right",
        )
        left_alias_name = "dex_sharpa_left_joint_aliases"
        right_alias_name = "dex_sharpa_right_joint_aliases"
    else:
        raise ValueError(
            f"Sharpa hand retargeting requires one of {SHARPA_HAND_RETARGETERS}, "
            f"got {context.resolved_hand_retargeter!r}"
        )

    left_hand_connected = left_hand_retargeter.connect(
        {HandsSource.LEFT: hands.output(HandsSource.LEFT)}
    )
    right_hand_connected = right_hand_retargeter.connect(
        {HandsSource.RIGHT: hands.output(HandsSource.RIGHT)}
    )
    left_finger_joints = maybe_alias_hand_joints(
        left_hand_connected,
        joint_names_from_group_type(left_hand_retargeter.output_spec()["hand_joints"]),
        context.left_finger_joint_name_aliases,
        left_alias_name,
    )
    right_finger_joints = maybe_alias_hand_joints(
        right_hand_connected,
        joint_names_from_group_type(right_hand_retargeter.output_spec()["hand_joints"]),
        context.right_finger_joint_name_aliases,
        right_alias_name,
    )
    return left_finger_joints, right_finger_joints


def maybe_alias_hand_joints(
    connected_hand_retargeter,
    input_joint_names: Sequence[str],
    output_joint_names: Sequence[str] | None,
    name: str,
):
    if output_joint_names is None:
        return connected_hand_retargeter.output("hand_joints")

    alias_retargeter = JointNameAliasRetargeter(
        input_joint_names=input_joint_names,
        output_joint_names=output_joint_names,
        name=name,
    )
    alias_connected = alias_retargeter.connect(
        {"hand_joints": connected_hand_retargeter.output("hand_joints")}
    )
    return alias_connected.output("hand_joints")


def validate_joint_name_alias_count(
    parameter_name: str,
    aliases: Sequence[str] | None,
    expected_count: int,
) -> None:
    if aliases is None:
        return
    if len(aliases) != expected_count:
        raise ValueError(
            f"Parameter '{parameter_name}' must contain exactly {expected_count} "
            f"joint name aliases, got {len(aliases)}"
        )
