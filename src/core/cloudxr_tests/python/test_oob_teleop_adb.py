# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_adb` (hints, device validation, bookmark automation with mocked subprocess)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cloudxr_py_test_ns.oob_teleop_adb import (
    OobAdbError,
    adb_automation_failure_hint,
    adb_device_state,
    assert_adb_device_online,
    assert_exactly_one_adb_device,
    coturn_binary_path,
    oob_adb_automation_message,
    require_adb_on_path,
    require_coturn_available,
    run_adb_headset_bookmark,
)


@pytest.fixture(autouse=True)
def _clear_adb_device_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make device-selection tests independent of the developer's shell env."""
    monkeypatch.delenv("ANDROID_SERIAL", raising=False)


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
def test_assert_exactly_one_adb_device_pin_via_android_serial(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two devices, but ANDROID_SERIAL pins one — accept and proceed.
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nABC123\tdevice\nDEF456\tdevice\n\n",
        stderr="",
    )
    monkeypatch.setenv("ANDROID_SERIAL", "DEF456")
    assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_adb_device_pin_unknown_serial_raises(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operator pinned a serial that is not actually connected — error
    # surfaces the ones that are, so they can fix the typo.
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nABC123\tdevice\nDEF456\tdevice\n\n",
        stderr="",
    )
    monkeypatch.setenv("ANDROID_SERIAL", "GHI789")
    with pytest.raises(OobAdbError, match="not currently in `device` state"):
        assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_too_many_hints_at_android_serial(
    mock_run: MagicMock,
) -> None:
    # The "too many devices" error must mention ANDROID_SERIAL so the
    # operator knows the disambiguation knob exists.
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="List of devices attached\nABC123\tdevice\nDEF456\tdevice\n\n",
        stderr="",
    )
    with pytest.raises(OobAdbError, match="ANDROID_SERIAL"):
        assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_assert_exactly_one_ignores_unauthorized(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=("List of devices attached\nABC123\tdevice\nDEF456\tunauthorized\n\n"),
        stderr="",
    )
    assert_exactly_one_adb_device()


@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="device")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.resolve_lan_host_for_oob",
    return_value="10.0.0.1",
)
def test_run_adb_headset_bookmark_success(
    mock_lan: MagicMock, mock_run: MagicMock, _mock_state: MagicMock
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    rc, diag = run_adb_headset_bookmark(resolved_port=48322)
    assert rc == 0
    assert diag == ""
    args = mock_run.call_args[0][0]
    assert args[0] == "adb"
    assert args[1] == "shell"
    assert "am start" in args[2]


@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="device")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.resolve_lan_host_for_oob",
    return_value="10.0.0.1",
)
def test_run_adb_headset_bookmark_failure(
    mock_lan: MagicMock, mock_run: MagicMock, _mock_state: MagicMock
) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no devices/emulators found"
    )
    rc, diag = run_adb_headset_bookmark(resolved_port=48322)
    assert rc == 1
    assert "no devices" in diag


# coturn binary lookup -------------------------------------------------------


@patch("cloudxr_py_test_ns.oob_teleop_adb.os.path.exists", return_value=False)
@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which")
def test_coturn_binary_path_prefers_turnserver(
    mock_which: MagicMock, _mock_exists: MagicMock
) -> None:
    mock_which.side_effect = lambda name: (
        "/usr/local/bin/turnserver" if name == "turnserver" else None
    )
    assert coturn_binary_path() == "/usr/local/bin/turnserver"


@patch("cloudxr_py_test_ns.oob_teleop_adb.os.path.exists", return_value=False)
@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which")
def test_coturn_binary_path_accepts_coturn_name(
    mock_which: MagicMock, _mock_exists: MagicMock
) -> None:
    mock_which.side_effect = lambda name: (
        "/opt/coturn/bin/coturn" if name == "coturn" else None
    )
    assert coturn_binary_path() == "/opt/coturn/bin/coturn"


@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which", return_value=None)
def test_coturn_binary_path_falls_back_to_usr_bin(mock_which: MagicMock) -> None:
    with patch(
        "cloudxr_py_test_ns.oob_teleop_adb.os.path.exists",
        side_effect=lambda p: p == "/usr/bin/coturn",
    ):
        assert coturn_binary_path() == "/usr/bin/coturn"


@patch("cloudxr_py_test_ns.oob_teleop_adb.shutil.which", return_value=None)
@patch("cloudxr_py_test_ns.oob_teleop_adb.os.path.exists", return_value=False)
def test_require_coturn_available_missing_mentions_both_names(
    _mock_exists: MagicMock, _mock_which: MagicMock
) -> None:
    with pytest.raises(OobAdbError) as excinfo:
        require_coturn_available()
    msg = str(excinfo.value)
    assert "turnserver" in msg and "coturn" in msg


# Device-state guard ---------------------------------------------------------


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_adb_device_state_device(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="device\n", stderr="")
    assert adb_device_state() == "device"


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_adb_device_state_unauthorized_via_stderr(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="error: device unauthorized\n"
    )
    assert "unauthorized" in adb_device_state()


@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.subprocess.run",
    side_effect=FileNotFoundError(),
)
def test_adb_device_state_no_adb(mock_run: MagicMock) -> None:
    assert adb_device_state() == ""


@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="device")
def test_assert_adb_device_online_ok(mock_state: MagicMock) -> None:
    assert_adb_device_online()


@pytest.mark.parametrize(
    "state,needle",
    [
        ("unauthorized", "unauthorized"),
        ("error: device unauthorized", "unauthorized"),
        ("", "not responding"),
        ("recovery", "expected `device`"),
    ],
)
def test_assert_adb_device_online_messages(state: str, needle: str) -> None:
    with patch(
        "cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value=state
    ):
        with pytest.raises(OobAdbError) as excinfo:
            assert_adb_device_online()
        assert needle.lower() in str(excinfo.value).lower()


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state")
@patch("cloudxr_py_test_ns.oob_teleop_adb.time.sleep")
def test_assert_adb_device_online_recovers_offline_via_reconnect(
    _mock_sleep: MagicMock, mock_state: MagicMock, mock_run: MagicMock
) -> None:
    mock_state.side_effect = ["offline", "device"]
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    assert_adb_device_online()  # should not raise
    cmd = mock_run.call_args[0][0]
    assert cmd == ["adb", "reconnect"]


@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state")
@patch("cloudxr_py_test_ns.oob_teleop_adb.time.sleep")
def test_assert_adb_device_online_offline_persists(
    _mock_sleep: MagicMock, mock_state: MagicMock, mock_run: MagicMock
) -> None:
    mock_state.side_effect = ["offline", "offline"]
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    with pytest.raises(OobAdbError, match="offline"):
        assert_adb_device_online()


@patch("cloudxr_py_test_ns.oob_teleop_adb.time.sleep")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="offline")
@patch(
    "cloudxr_py_test_ns.oob_teleop_adb.resolve_lan_host_for_oob",
    return_value="10.0.0.1",
)
def test_run_adb_headset_bookmark_offline_returns_clean_diag(
    _mock_lan: MagicMock,
    _mock_state: MagicMock,
    _mock_run: MagicMock,
    _mock_sleep: MagicMock,
) -> None:
    rc, diag = run_adb_headset_bookmark(resolved_port=48322)
    assert rc != 0
    assert "offline" in diag.lower()


# Reverse-setup wraps subprocess errors as OobAdbError --------------------------


@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="device")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
def test_setup_adb_reverse_ports_wraps_called_process_error(
    mock_run: MagicMock, _mock_state: MagicMock
) -> None:
    from cloudxr_py_test_ns.oob_teleop_adb import (
        setup_adb_reverse_ports,
    )
    import subprocess as sp

    mock_run.side_effect = sp.CalledProcessError(
        returncode=1, cmd=["adb"], stderr="error: device offline"
    )
    with pytest.raises(OobAdbError) as excinfo:
        setup_adb_reverse_ports()
    msg = str(excinfo.value)
    assert "adb reverse" in msg
    assert "device offline" in msg


@patch("cloudxr_py_test_ns.oob_teleop_adb.time.sleep")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="offline")
def test_setup_adb_reverse_ports_offline_short_circuits(
    _mock_state: MagicMock, _mock_run: MagicMock, _mock_sleep: MagicMock
) -> None:
    from cloudxr_py_test_ns.oob_teleop_adb import (
        setup_adb_reverse_ports,
    )

    with pytest.raises(OobAdbError, match="offline"):
        setup_adb_reverse_ports()


@patch("cloudxr_py_test_ns.oob_teleop_adb.time.sleep")
@patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run")
@patch("cloudxr_py_test_ns.oob_teleop_adb.adb_device_state", return_value="offline")
def test_setup_adb_reverse_turn_offline_short_circuits(
    _mock_state: MagicMock, _mock_run: MagicMock, _mock_sleep: MagicMock
) -> None:
    from cloudxr_py_test_ns.oob_teleop_adb import (
        setup_adb_reverse_turn,
    )

    with pytest.raises(OobAdbError, match="offline"):
        setup_adb_reverse_turn(3478)


# WiFi-drop monitor (H6) -----------------------------------------------------


import asyncio  # noqa: E402

from cloudxr_py_test_ns.oob_teleop_adb import monitor_headset_wifi  # noqa: E402


async def test_monitor_headset_wifi_warns_on_drop(capsys) -> None:
    # Sequence: had ifaces → still ifaces → drops → still dropped.
    seq = [
        [("wlan0", "10.0.0.1")],
        [("wlan0", "10.0.0.1")],
        [],
        [],
    ]
    with patch(
        "cloudxr_py_test_ns.oob_teleop_adb.headset_non_loopback_interfaces",
        side_effect=lambda: seq.pop(0) if seq else [],
    ):
        task = asyncio.create_task(monitor_headset_wifi(poll_seconds=0.001))
        # Poll for the warning rather than racing a fixed sleep budget. On
        # Windows, asyncio.sleep resolution (~15ms timer tick) plus to_thread
        # dispatch makes the two loop iterations needed to detect the drop
        # blow past a 50ms budget.
        out = ""
        for _ in range(200):  # up to ~2s
            await asyncio.sleep(0.01)
            out += capsys.readouterr().err
            if "Headset Wi-Fi dropped" in out:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    out += capsys.readouterr().err
    assert "Headset Wi-Fi dropped" in out
    # Reason should be spelled out so operators don't think USB-local removed the WiFi requirement.
    assert "required even in USB-local mode" in out


async def test_monitor_headset_wifi_silent_when_steady(capsys) -> None:
    with patch(
        "cloudxr_py_test_ns.oob_teleop_adb.headset_non_loopback_interfaces",
        return_value=[("wlan0", "10.0.0.1")],
    ):
        task = asyncio.create_task(monitor_headset_wifi(poll_seconds=0.001))
        await asyncio.sleep(0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert capsys.readouterr().err == ""


# Coturn watchdog (H7) -------------------------------------------------------


from cloudxr_py_test_ns.oob_teleop_adb import watch_coturn  # noqa: E402


from cloudxr_py_test_ns.oob_teleop_adb import _teleop_error_hint  # noqa: E402


@pytest.mark.parametrize(
    "banner,needle",
    [
        ("CloudXR session stopped (0xC0F2220F)", "ICE candidates"),
        ("No local connection candidates", "ICE candidates"),
        ("wss connection close 1006", "WSS dropped"),
        ("something unrelated", ""),
    ],
)
def test_teleop_error_hint(banner: str, needle: str) -> None:
    hint = _teleop_error_hint(banner)
    if needle:
        assert needle.lower() in hint.lower()
    else:
        assert hint == ""


async def test_watch_coturn_restarts_once_then_gives_up(capsys) -> None:
    dead_proc = MagicMock()
    dead_proc.poll.return_value = 1
    dead_proc.returncode = 1
    proc_box = [dead_proc]
    new_proc = MagicMock(pid=4242)
    new_proc.poll.return_value = 1  # also dead, triggers give-up
    new_proc.returncode = 1

    with (
        patch(
            "cloudxr_py_test_ns.oob_teleop_adb.start_coturn", return_value=new_proc
        ) as mock_start,
        patch(
            "cloudxr_py_test_ns.oob_teleop_adb._tail_file", return_value="<log tail>"
        ),
    ):
        task = asyncio.create_task(
            watch_coturn(
                proc_box,
                turn_port=3478,
                user="u",
                credential="c",
                poll_seconds=0.001,
            )
        )
        await asyncio.wait_for(task, timeout=1.0)
    assert mock_start.call_count == 1
    assert proc_box[0] is new_proc
    assert "died again" in capsys.readouterr().err
