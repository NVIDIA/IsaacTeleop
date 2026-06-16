# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Teleop launch option normalization."""

from __future__ import annotations

import pytest

from oob_teleop_options import (
    DEVICE_AUTOMATION_NONE,
    DEVICE_AUTOMATION_XRHMD,
    TRANSPORT_USB,
    TRANSPORT_WIFI,
    normalize_teleop_launch_options,
)


def test_defaults_are_manual_wifi_without_hub() -> None:
    opts = normalize_teleop_launch_options()

    assert opts.hub is False
    assert opts.host_client is False
    assert opts.transport == TRANSPORT_WIFI
    assert opts.device_automation == DEVICE_AUTOMATION_NONE
    assert opts.usb_local is False
    assert opts.setup_oob is False


def test_future_api_combination_is_preserved() -> None:
    opts = normalize_teleop_launch_options(
        hub=True,
        host_client=True,
        transport="usb",
        device_automation="xrhmd",
    )

    assert opts.hub is True
    assert opts.host_client is True
    assert opts.transport == TRANSPORT_USB
    assert opts.device_automation == DEVICE_AUTOMATION_XRHMD
    assert opts.usb_local is True
    assert opts.setup_oob is True
    assert opts.deprecation_warnings == ()


def test_usb_transport_can_run_without_hub_or_automation() -> None:
    opts = normalize_teleop_launch_options(transport="usb")

    assert opts.hub is False
    assert opts.host_client is False
    assert opts.transport == TRANSPORT_USB
    assert opts.device_automation == DEVICE_AUTOMATION_NONE
    assert opts.usb_local is True
    assert opts.setup_oob is False


def test_setup_oob_is_legacy_alias_for_hub_xrhmd_wifi() -> None:
    opts = normalize_teleop_launch_options(setup_oob=True)

    assert opts.hub is True
    assert opts.transport == TRANSPORT_WIFI
    assert opts.device_automation == DEVICE_AUTOMATION_XRHMD
    assert opts.deprecation_warnings


def test_usb_local_is_legacy_alias_for_full_usb_flow() -> None:
    opts = normalize_teleop_launch_options(usb_local=True)

    assert opts.hub is True
    assert opts.host_client is True
    assert opts.transport == TRANSPORT_USB
    assert opts.device_automation == DEVICE_AUTOMATION_XRHMD
    assert opts.deprecation_warnings


def test_xrhmd_automation_requires_hub() -> None:
    with pytest.raises(ValueError, match="requires --hub"):
        normalize_teleop_launch_options(device_automation="xrhmd")


def test_legacy_aliases_conflict_with_explicit_none() -> None:
    with pytest.raises(ValueError, match="setup-oob conflicts"):
        normalize_teleop_launch_options(setup_oob=True, device_automation="none")

    with pytest.raises(ValueError, match="usb-local conflicts"):
        normalize_teleop_launch_options(usb_local=True, device_automation="none")


def test_usb_local_conflicts_with_explicit_wifi() -> None:
    with pytest.raises(ValueError, match="transport wifi"):
        normalize_teleop_launch_options(usb_local=True, transport="wifi")
