# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for resolved teleoperation runtime profiles."""

from types import SimpleNamespace

import pytest

import session_config
from constants import (
    TELEOP_MODES,
    HandRetargeter,
    TeleopMode,
    resolve_hand_retargeter,
)
from session_config import validate_joint_name_alias_count
from teleop_profiles import (
    TELEOP_PROFILE_SPECS,
    PublishType,
    TeleopProfile,
    TeleopProfileSpec,
    resolve_teleop_profile_spec,
    validate_session_result,
)


def _frame_for(profile_spec: TeleopProfileSpec) -> dict:
    return {key: object() for key in profile_spec.required_result_keys}


def test_every_profile_has_a_spec() -> None:
    assert tuple(mode.value for mode in TeleopMode) == TELEOP_MODES
    assert set(TELEOP_PROFILE_SPECS) == set(TeleopProfile)
    assert {spec.mode for spec in TELEOP_PROFILE_SPECS.values()} == set(TeleopMode)


@pytest.mark.parametrize(
    ("mode", "builder_name"),
    (
        (TeleopMode.CONTROLLER_TELEOP, "build_controller_teleop_config"),
        (TeleopMode.HAND_TELEOP, "build_hand_teleop_config"),
        (TeleopMode.CONTROLLER_RAW, "build_controller_raw_config"),
        (TeleopMode.FULL_BODY, "build_full_body_config"),
    ),
)
def test_session_config_dispatches_each_mode(
    monkeypatch, mode: TeleopMode, builder_name: str
) -> None:
    expected_config = object()
    monkeypatch.setattr(
        session_config,
        builder_name,
        lambda _params: expected_config,
    )

    assert (
        session_config.build_session_config(SimpleNamespace(mode=mode))
        is expected_config
    )


def test_controller_profile_spec_is_resolved_for_selected_retargeter() -> None:
    controller_spec = resolve_teleop_profile_spec(
        TeleopMode.CONTROLLER_TELEOP, HandRetargeter.TRIHAND
    )
    hands_spec = resolve_teleop_profile_spec(
        TeleopMode.CONTROLLER_TELEOP, HandRetargeter.DEXPILOT
    )

    assert "hand_left" not in controller_spec.required_result_keys
    assert "hand_right" not in controller_spec.required_result_keys
    assert PublishType.HAND_POSES not in controller_spec.publish_types

    assert {"hand_left", "hand_right"} <= hands_spec.required_result_keys
    assert PublishType.HAND_POSES in hands_spec.publish_types


@pytest.mark.parametrize(
    ("retargeter", "expected_profile"),
    (
        (HandRetargeter.TRIHAND, TeleopProfile.CONTROLLER_TELEOP),
        (HandRetargeter.DEXPILOT, TeleopProfile.CONTROLLER_TELEOP_WITH_HANDS),
        (HandRetargeter.PINK_IK, TeleopProfile.CONTROLLER_TELEOP_WITH_HANDS),
    ),
)
def test_controller_profile_spec_resolution(
    retargeter: HandRetargeter, expected_profile: TeleopProfile
) -> None:
    profile_spec = resolve_teleop_profile_spec(TeleopMode.CONTROLLER_TELEOP, retargeter)
    assert profile_spec is TELEOP_PROFILE_SPECS[expected_profile]


@pytest.mark.parametrize("profile", list(TeleopProfile))
def test_valid_session_result_is_accepted(profile: TeleopProfile) -> None:
    profile_spec = TELEOP_PROFILE_SPECS[profile]
    result = _frame_for(profile_spec)

    assert validate_session_result(result, profile_spec) is result


def test_session_result_reports_missing_and_unexpected_keys() -> None:
    profile_spec = TELEOP_PROFILE_SPECS[TeleopProfile.CONTROLLER_RAW]
    result = _frame_for(profile_spec)
    result.pop("controller_left")
    result["head"] = object()

    with pytest.raises(
        ValueError,
        match=r"missing keys: \['controller_left'\].*unexpected keys: \['head'\]",
    ):
        validate_session_result(result, profile_spec)


def test_mode_default_retargeters_are_resolved_centrally() -> None:
    assert (
        resolve_hand_retargeter(
            TeleopMode.CONTROLLER_TELEOP, HandRetargeter.MODE_DEFAULT
        )
        == HandRetargeter.TRIHAND
    )
    assert (
        resolve_hand_retargeter(TeleopMode.HAND_TELEOP, HandRetargeter.MODE_DEFAULT)
        == HandRetargeter.DEXPILOT
    )


def test_trihand_is_rejected_for_hand_teleop() -> None:
    with pytest.raises(ValueError, match="only valid with mode:=controller_teleop"):
        resolve_hand_retargeter(TeleopMode.HAND_TELEOP, HandRetargeter.TRIHAND)


def test_joint_alias_count_validation() -> None:
    validate_joint_name_alias_count("left_finger_joint_names", None, 2)
    validate_joint_name_alias_count("left_finger_joint_names", ["a", "b"], 2)

    with pytest.raises(ValueError, match="must contain exactly 2"):
        validate_joint_name_alias_count("left_finger_joint_names", ["a"], 2)
