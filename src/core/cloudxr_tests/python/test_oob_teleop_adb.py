# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_adb` (CLI parsing, hints, adb reverse, relay, bookmark automation with mocked subprocess)."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from cloudxr_py_test_ns.oob_teleop_adb import (
    AdbAutomation,
    OobAdbError,
    adb_automation_failure_hint,
    adb_automation_from_setup_oob,
    adb_push_file,
    adb_reverse,
    adb_reverse_remove_all,
    adb_start_relay,
    adb_stop_relay,
    assert_at_most_one_adb_device,
    ensure_adb_connect,
    oob_adb_automation_message,
    parse_setup_oob_cli,
    require_adb_on_path,
    run_adb_headset_bookmark,
    setup_adb_reverse_ports,
)


def test_adb_automation_from_setup_oob_tethered() -> None:
    a = adb_automation_from_setup_oob("  TETHERED  ")
    assert a == AdbAutomation(tethered=True, connect=None)


def test_adb_automation_from_setup_oob_wireless() -> None:
    a = adb_automation_from_setup_oob("192.168.1.5:5555")
    assert a == AdbAutomation(tethered=False, connect="192.168.1.5:5555")


def test_adb_automation_from_setup_oob_invalid() -> None:
    with pytest.raises(ValueError, match="tethered"):
        adb_automation_from_setup_oob("nocolon")


def test_parse_setup_oob_cli() -> None:
    assert parse_setup_oob_cli("tethered") == "tethered"
    assert parse_setup_oob_cli("10.0.0.1:5555") == "10.0.0.1:5555"
    with pytest.raises(argparse.ArgumentTypeError):
        parse_setup_oob_cli("")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_setup_oob_cli("bad")


@pytest.mark.parametrize(
    "diag,needle",
    [
        ("device unauthorized", "unauthorized"),
        ("error: no devices/emulators found", "No adb device"),
        ("error: no devices found", "No adb device"),
        ("device not found", "No adb device"),
        ("more than one device", "Multiple adb devices"),
        ("device offline", "offline"),
        ("something else", ""),
    ],
)
def test_adb_automation_failure_hint(diag: str, needle: str) -> None:
    h = adb_automation_failure_hint(diag)
    if needle:
        assert needle.lower() in h.lower()
    else:
        assert h == ""


def test_oob_adb_automation_message_format() -> None:
    msg = oob_adb_automation_message(1, "adb said no", "try again")
    assert "exit code 1" in msg
    assert "adb said no" in msg
    assert "try again" in msg
    assert "omit --setup-oob" in msg


def test_oob_adb_automation_message_empty_detail() -> None:
    msg = oob_adb_automation_message(2, "", "")
    assert "(no output from adb)" in msg


def test_require_adb_on_path_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_adb.shutil.which", lambda _x: None
    )
    with pytest.raises(OobAdbError, match="adb` was not found"):
        require_adb_on_path()


def test_require_adb_on_path_ok_when_adb_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_adb.shutil.which", lambda _x: "/fake/adb"
    )
    require_adb_on_path()


def test_ensure_adb_connect_skips_empty() -> None:
    with patch("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run") as run:
        ensure_adb_connect("  \t  ")
        run.assert_not_called()


def test_ensure_adb_connect_invokes_adb(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        called.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = m.stderr = ""
        return m

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    ensure_adb_connect("192.168.0.5:5555")
    assert called == [["adb", "connect", "192.168.0.5:5555"]]


def test_assert_at_most_one_adb_device_two_devices_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = "List of devices attached\nserial1\tdevice\nserial2\tdevice\n"
        return m

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    with pytest.raises(OobAdbError, match="Too many adb devices"):
        assert_at_most_one_adb_device()


def test_assert_at_most_one_adb_device_one_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = "List of devices attached\nabc\tdevice\n"
        return m

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    assert_at_most_one_adb_device()


def test_assert_at_most_one_adb_file_not_found_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_a: object, **_kw: object) -> None:
        raise FileNotFoundError("adb")

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    with pytest.raises(OobAdbError, match="adb` was not found"):
        assert_at_most_one_adb_device()


def _proc(rc: int, out: str = "", err: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = rc
    m.stdout = out
    m.stderr = err
    return m


# ── adb reverse tests ──


def test_adb_reverse_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    adb_reverse(48322, 48322)
    assert calls == [["adb", "reverse", "tcp:48322", "tcp:48322"]]


def test_adb_reverse_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_adb.subprocess.run",
        lambda *a, **kw: _proc(1, err="error: device offline"),
    )
    with pytest.raises(OobAdbError, match="adb reverse"):
        adb_reverse(48322, 48322)


def test_adb_reverse_remove_all_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    adb_reverse_remove_all()
    assert calls == [["adb", "reverse", "--remove-all"]]


def test_setup_adb_reverse_ports_with_web(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    ports = setup_adb_reverse_ports(48322, 47999, web_port=8080)
    assert ports == [48322, 47999, 8080]
    assert len(calls) == 3


def test_setup_adb_reverse_ports_no_web(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    ports = setup_adb_reverse_ports(48322, 47999)
    assert ports == [48322, 47999]
    assert len(calls) == 2


# ── adb push / relay tests ──


def test_adb_push_file_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    adb_push_file("/tmp/udprelay", "/data/local/tmp/udprelay")
    assert calls == [["adb", "push", "/tmp/udprelay", "/data/local/tmp/udprelay"]]


def test_adb_push_file_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_adb.subprocess.run",
        lambda *a, **kw: _proc(1, err="push failed"),
    )
    with pytest.raises(OobAdbError, match="adb push"):
        adb_push_file("/tmp/udprelay", "/data/local/tmp/udprelay")


def test_adb_start_relay_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    adb_start_relay("/data/local/tmp/udprelay", 47998, 47999)
    assert len(calls) == 2  # chmod + nohup


def test_adb_stop_relay_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(1)  # process not found is ok

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    adb_stop_relay("/data/local/tmp/udprelay")
    assert any("pkill" in c for c in calls)


# ── bookmark tests ──


def test_run_adb_headset_bookmark_wireless_am_start_ok(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "192.168.0.7")
    monkeypatch.delenv("TELEOP_WEB_CLIENT_BASE", raising=False)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    rc, diag = run_adb_headset_bookmark(
        resolved_port=48322,
        adb=AdbAutomation(tethered=False, connect=None),
    )
    assert rc == 0
    assert diag == ""
    assert len(calls) == 1
    assert calls[0][:2] == ["adb", "shell"]
    assert "-d" in calls[0]
    intent_url = calls[0][calls[0].index("-d") + 1]
    assert "oobEnable=1" in intent_url
    assert "192.168.0.7" in intent_url


def test_run_adb_headset_bookmark_tethered_uses_loopback(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEOP_WEB_CLIENT_BASE", raising=False)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        calls.append(cmd)
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    rc, diag = run_adb_headset_bookmark(
        resolved_port=48322,
        adb=AdbAutomation(tethered=True, connect=None),
    )
    assert rc == 0
    assert diag == ""
    assert len(calls) == 1
    intent_url = calls[0][calls[0].index("-d") + 1]
    assert intent_url.startswith("https://127.0.0.1:8080/"), (
        f"tethered mode should use local web client, got: {intent_url}"
    )
    assert "oobEnable=1" in intent_url
    assert "serverIP=127.0.0.1" in intent_url
    # mediaAddress/mediaPort must NOT be set — WebRTC ICE rejects loopback
    # as a remote candidate.  Media negotiates via normal ICE (WiFi).
    assert "mediaAddress" not in intent_url
    assert "mediaPort" not in intent_url


def test_run_adb_headset_bookmark_am_start_failure(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "10.0.0.1")
    monkeypatch.delenv("TELEOP_WEB_CLIENT_BASE", raising=False)

    def fake_run(cmd: list[str], **_kw: object) -> MagicMock:
        if "am" in cmd and "VIEW" in " ".join(cmd):
            return _proc(1, err="am start failed")
        return _proc(0)

    monkeypatch.setattr("cloudxr_py_test_ns.oob_teleop_adb.subprocess.run", fake_run)
    rc, diag = run_adb_headset_bookmark(
        resolved_port=48322,
        adb=AdbAutomation(tethered=False, connect=None),
    )
    assert rc == 1
    assert "am start failed" in diag


# Re-use fixture name from test_oob_teleop_env pattern
@pytest.fixture
def clear_teleop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "TELEOP_PROXY_HOST",
        "TELEOP_WEB_CLIENT_BASE",
        "TELEOP_STREAM_SERVER_IP",
        "TELEOP_STREAM_PORT",
        "TELEOP_STREAM_MEDIA_PORT",
        "CONTROL_TOKEN",
        "TELEOP_CLIENT_CODEC",
        "TELEOP_CLIENT_PANEL_HIDDEN_AT_START",
        "TELEOP_CLIENT_PER_EYE_WIDTH",
        "TELEOP_CLIENT_PER_EYE_HEIGHT",
    ):
        monkeypatch.delenv(k, raising=False)
