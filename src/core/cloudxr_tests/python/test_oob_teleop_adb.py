# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_adb` (hints, device validation, bookmark automation with mocked subprocess)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cloudxr_py_test_ns.oob_teleop_adb import (
    OobAdbError,
    adb_automation_failure_hint,
    assert_exactly_one_adb_device,
    oob_adb_automation_message,
    require_adb_on_path,
    run_adb_headset_bookmark,
)


@pytest.mark.parametrize(
    "diag,needle",
    [
        ("device unauthorized", "unauthorized"),
        ("no devices/emulators found", "No adb device"),
        ("device not found", "No adb device"),
        ("more than one device or emulator", "Multiple adb devices"),
        ("device offline", "offline"),
    ],
)
def test_adb_automation_failure_hint(diag: str, needle: str) -> None:
    hint = adb_automation_failure_hint(diag)
    assert needle.lower() in hint.lower()


def test_adb_automation_failure_hint_unknown() -> None:
    assert adb_automation_failure_hint("unknown error") == ""


def test_oob_adb_automation_message() -> None:
    msg = oob_adb_automation_message(1, "device offline", "Device offline hint.")
    assert "exit code 1" in msg
    assert "device offline" in msg
    assert "Device offline hint." in msg
    assert "omit --setup-oob" in msg


def test_oob_adb_automation_message_empty_detail() -> None:
    msg = oob_adb_automation_message(2, "", "")
    assert "no output from adb" in msg


@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which", return_value="/usr/bin/adb")
def test_require_adb_on_path_found(mock_which: MagicMock) -> None:
    require_adb_on_path()


@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which", return_value=None)
def test_require_adb_on_path_missing(mock_which: MagicMock) -> None:
    with pytest.raises(OobAdbError, match="not found on PATH"):
        require_adb_on_path()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_adb_device_zero_raises(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\n\n",
        stderr="",
    )
    with pytest.raises(OobAdbError, match="No adb device"):
        assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_adb_device_one(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nABC123\tdevice\n\n",
        stderr="",
    )
    assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_adb_device_two_raises(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=("List of devices attached\nABC123\tdevice\nDEF456\tdevice\n\n"),
        stderr="",
    )
    with pytest.raises(OobAdbError, match="Too many"):
        assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_ignores_unauthorized(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=("List of devices attached\nABC123\tdevice\nDEF456\tunauthorized\n\n"),
        stderr="",
    )
    assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.resolve_lan_host_for_oob",
    return_value="10.0.0.1",
)
def test_run_adb_headset_bookmark_success(
    mock_lan: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    rc, diag = run_adb_headset_bookmark(resolved_port=48322)
    assert rc == 0
    assert diag == ""
    args = mock_run.call_args[0][0]
    assert args[0] == "adb"
    assert args[1] == "shell"
    assert "am start" in args[2]


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.resolve_lan_host_for_oob",
    return_value="10.0.0.1",
)
def test_run_adb_headset_bookmark_failure(
    mock_lan: MagicMock, mock_run: MagicMock
) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no devices/emulators found"
    )
    rc, diag = run_adb_headset_bookmark(resolved_port=48322)
    assert rc == 1
    assert "no devices" in diag
