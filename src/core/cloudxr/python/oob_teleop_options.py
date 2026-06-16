# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Launch option normalization for the Teleop hub/client/device split."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TRANSPORT_WIFI = "wifi"
TRANSPORT_USB = "usb"
TRANSPORTS = (TRANSPORT_WIFI, TRANSPORT_USB)

DEVICE_AUTOMATION_NONE = "none"
DEVICE_AUTOMATION_XRHMD = "xrhmd"
DEVICE_AUTOMATIONS = (DEVICE_AUTOMATION_NONE, DEVICE_AUTOMATION_XRHMD)

Transport = Literal["wifi", "usb"]
DeviceAutomation = Literal["none", "xrhmd"]


@dataclass(frozen=True)
class TeleopLaunchOptions:
    """Normalized launch options for the Teleop service/client/topology split."""

    hub: bool = False
    host_client: bool = False
    transport: Transport = TRANSPORT_WIFI
    device_automation: DeviceAutomation = DEVICE_AUTOMATION_NONE
    deprecation_warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usb_local(self) -> bool:
        """Compatibility view for the current USB-local implementation."""
        return self.transport == TRANSPORT_USB

    @property
    def setup_oob(self) -> bool:
        """Compatibility view for the current Android HMD automation path."""
        return self.device_automation == DEVICE_AUTOMATION_XRHMD


def normalize_teleop_launch_options(
    *,
    hub: bool = False,
    host_client: bool = False,
    transport: str | None = None,
    device_automation: str | None = None,
    setup_oob: bool = False,
    usb_local: bool = False,
) -> TeleopLaunchOptions:
    """Normalize future-facing options plus deprecated compatibility aliases."""
    requested_transport = _normalize_transport(transport)
    requested_automation = _normalize_device_automation(device_automation)
    transport_explicit = transport is not None
    automation_explicit = device_automation is not None

    normalized_hub = bool(hub)
    normalized_host_client = bool(host_client)
    normalized_transport = requested_transport or TRANSPORT_WIFI
    normalized_automation = requested_automation or DEVICE_AUTOMATION_NONE
    warnings: list[str] = []

    if setup_oob:
        warnings.append(
            "--setup-oob is deprecated; use "
            "--hub --transport wifi --device-automation xrhmd."
        )
        normalized_hub = True
        if automation_explicit and normalized_automation != DEVICE_AUTOMATION_XRHMD:
            raise ValueError(
                "--setup-oob conflicts with --device-automation none; "
                "use --hub without --setup-oob for a hub-only run."
            )
        normalized_automation = DEVICE_AUTOMATION_XRHMD

    if usb_local:
        warnings.append(
            "--usb-local is deprecated; use "
            "--hub --host-client --transport usb --device-automation xrhmd."
        )
        normalized_hub = True
        normalized_host_client = True
        if transport_explicit and normalized_transport != TRANSPORT_USB:
            raise ValueError("--usb-local conflicts with --transport wifi.")
        normalized_transport = TRANSPORT_USB
        if automation_explicit and normalized_automation != DEVICE_AUTOMATION_XRHMD:
            raise ValueError(
                "--usb-local conflicts with --device-automation none; "
                "use --transport usb without --usb-local for manual USB topology."
            )
        normalized_automation = DEVICE_AUTOMATION_XRHMD

    if normalized_automation == DEVICE_AUTOMATION_XRHMD and not normalized_hub:
        raise ValueError("--device-automation xrhmd currently requires --hub.")

    return TeleopLaunchOptions(
        hub=normalized_hub,
        host_client=normalized_host_client,
        transport=normalized_transport,  # type: ignore[arg-type]
        device_automation=normalized_automation,  # type: ignore[arg-type]
        deprecation_warnings=tuple(warnings),
    )


def _normalize_transport(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v not in TRANSPORTS:
        raise ValueError(
            f"transport must be one of {', '.join(TRANSPORTS)}; got {value!r}"
        )
    return v


def _normalize_device_automation(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v not in DEVICE_AUTOMATIONS:
        raise ValueError(
            "device_automation must be one of "
            f"{', '.join(DEVICE_AUTOMATIONS)}; got {value!r}"
        )
    return v
