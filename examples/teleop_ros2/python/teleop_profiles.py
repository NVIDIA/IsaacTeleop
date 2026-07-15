# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Resolved runtime profiles for teleoperation session results and publishing."""

from dataclasses import dataclass
from typing import Mapping, TypedDict, cast

from isaacteleop.retargeting_engine.interface import OptionalTensorGroup

from constants import SHARPA_HAND_RETARGETERS, HandRetargeter, StrEnum, TeleopMode


class FramePublication(StrEnum):
    CONTROLLER_PAYLOAD = "controller_payload"
    EE_FROM_CONTROLLERS = "ee_from_controllers"
    EE_FROM_HANDS = "ee_from_hands"
    FINGER_JOINTS = "finger_joints"
    FULL_BODY_PAYLOAD = "full_body_payload"
    HAND_POSES = "hand_poses"
    HEAD = "head"
    ROOT_COMMAND = "root_command"


class TeleopProfile(StrEnum):
    CONTROLLER_TELEOP = "controller_teleop"
    CONTROLLER_TELEOP_WITH_HANDS = "controller_teleop_with_hands"
    HAND_TELEOP = "hand_teleop"
    CONTROLLER_RAW = "controller_raw"
    FULL_BODY = "full_body"


class SessionResult(TypedDict, total=False):
    controller_left: OptionalTensorGroup
    controller_right: OptionalTensorGroup
    finger_joints_left: OptionalTensorGroup
    finger_joints_right: OptionalTensorGroup
    full_body: OptionalTensorGroup
    hand_left: OptionalTensorGroup
    hand_right: OptionalTensorGroup
    head: OptionalTensorGroup
    root_command: OptionalTensorGroup


@dataclass(frozen=True)
class TeleopProfileSpec:
    """Describe the frame inputs and publish paths for one resolved profile."""

    mode: TeleopMode
    required_result_keys: frozenset[str]
    publications: frozenset[FramePublication]


TELEOP_PROFILE_SPECS = {
    TeleopProfile.CONTROLLER_TELEOP: TeleopProfileSpec(
        mode=TeleopMode.CONTROLLER_TELEOP,
        required_result_keys=frozenset(
            {
                "controller_left",
                "controller_right",
                "finger_joints_left",
                "finger_joints_right",
                "head",
                "root_command",
            }
        ),
        publications=frozenset(
            {
                FramePublication.CONTROLLER_PAYLOAD,
                FramePublication.EE_FROM_CONTROLLERS,
                FramePublication.FINGER_JOINTS,
                FramePublication.HEAD,
                FramePublication.ROOT_COMMAND,
            }
        ),
    ),
    TeleopProfile.CONTROLLER_TELEOP_WITH_HANDS: TeleopProfileSpec(
        mode=TeleopMode.CONTROLLER_TELEOP,
        required_result_keys=frozenset(
            {
                "controller_left",
                "controller_right",
                "finger_joints_left",
                "finger_joints_right",
                "hand_left",
                "hand_right",
                "head",
                "root_command",
            }
        ),
        publications=frozenset(
            {
                FramePublication.CONTROLLER_PAYLOAD,
                FramePublication.EE_FROM_CONTROLLERS,
                FramePublication.FINGER_JOINTS,
                FramePublication.HAND_POSES,
                FramePublication.HEAD,
                FramePublication.ROOT_COMMAND,
            }
        ),
    ),
    TeleopProfile.HAND_TELEOP: TeleopProfileSpec(
        mode=TeleopMode.HAND_TELEOP,
        required_result_keys=frozenset(
            {
                "finger_joints_left",
                "finger_joints_right",
                "hand_left",
                "hand_right",
                "head",
                "root_command",
            }
        ),
        publications=frozenset(
            {
                FramePublication.EE_FROM_HANDS,
                FramePublication.FINGER_JOINTS,
                FramePublication.HAND_POSES,
                FramePublication.HEAD,
                FramePublication.ROOT_COMMAND,
            }
        ),
    ),
    TeleopProfile.CONTROLLER_RAW: TeleopProfileSpec(
        mode=TeleopMode.CONTROLLER_RAW,
        required_result_keys=frozenset({"controller_left", "controller_right"}),
        publications=frozenset({FramePublication.CONTROLLER_PAYLOAD}),
    ),
    TeleopProfile.FULL_BODY: TeleopProfileSpec(
        mode=TeleopMode.FULL_BODY,
        required_result_keys=frozenset(
            {"controller_left", "controller_right", "full_body"}
        ),
        publications=frozenset(
            {
                FramePublication.CONTROLLER_PAYLOAD,
                FramePublication.FULL_BODY_PAYLOAD,
            }
        ),
    ),
}


def resolve_teleop_profile_spec(
    mode: TeleopMode, resolved_hand_retargeter: HandRetargeter
) -> TeleopProfileSpec:
    """Resolve user-facing settings to one complete immutable runtime profile."""
    if (
        mode == TeleopMode.CONTROLLER_TELEOP
        and resolved_hand_retargeter in SHARPA_HAND_RETARGETERS
    ):
        profile = TeleopProfile.CONTROLLER_TELEOP_WITH_HANDS
    else:
        profile = TeleopProfile(mode.value)
    return TELEOP_PROFILE_SPECS[profile]


def validate_session_result(
    result: Mapping[str, OptionalTensorGroup],
    profile_spec: TeleopProfileSpec,
) -> SessionResult:
    """Validate and type-narrow a session frame against its profile contract."""
    expected_keys = profile_spec.required_result_keys
    actual_keys = frozenset(result)
    missing_keys = expected_keys - actual_keys
    unexpected_keys = actual_keys - expected_keys
    if missing_keys or unexpected_keys:
        details = []
        if missing_keys:
            details.append(f"missing keys: {sorted(missing_keys)}")
        if unexpected_keys:
            details.append(f"unexpected keys: {sorted(unexpected_keys)}")
        raise ValueError(
            f"Invalid session result for mode {profile_spec.mode.value!r}: "
            f"{'; '.join(details)}"
        )
    return cast(SessionResult, result)
