# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._core: level names, TRACE, log_dir()
and its ownership checks, and the line format both languages render with."""

from __future__ import annotations

import io
import logging
import os
import re
import stat
import tempfile
from pathlib import Path

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _console, _core

pytestmark = pytest.mark.usefixtures("_restore_console_state")


def test_trace_level_value_and_name():
    assert logging_config.TRACE == 5
    assert logging.getLevelName(5) == "TRACE"


def test_trace_is_below_debug_and_filtered_by_default():
    logger = logging.getLogger("isaacteleop.test_trace_filtering")
    logging_config.set_console_level("debug")  # still above TRACE
    handler = _console.ensure_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.log(logging_config.TRACE, "should not appear")
        logger.debug("should appear")
    finally:
        handler.stream = original_stream

    assert "should not appear" not in stream.getvalue()
    assert "should appear" in stream.getvalue()


def test_trace_visible_once_console_level_lowered_to_trace():
    logger = logging.getLogger("isaacteleop.test_trace_opt_in")
    logging_config.set_console_level("trace")
    handler = _console.ensure_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.log(logging_config.TRACE, "now visible")
    finally:
        handler.stream = original_stream

    assert "now visible" in stream.getvalue()


def test_resolve_level_is_case_insensitive():
    assert _core.resolve_level("DEBUG") == logging.DEBUG
    assert _core.resolve_level("Warning") == logging.WARNING


def test_resolve_level_rejects_unknown_name():
    with pytest.raises(ValueError):
        _core.resolve_level("nope")


def test_line_format_shape():
    """Both languages render this shape: a millisecond timestamp, a 5-wide
    level name, the logger name, a pid field, then the message. Nothing in the
    repository asserted it before -- a formatter swapped for
    ``logging.Formatter("%(message)s")`` would leave every prior test green,
    since they all only ever grepped for a marker string inside the line.
    """
    record = logging.LogRecord(
        "isaacteleop.test_line_format",
        logging.WARNING,
        __file__,
        1,
        "hello",
        None,
        None,
    )
    formatter = logging.Formatter(_core.LINE_FORMAT, datefmt=_core.DATE_FORMAT)
    line = formatter.format(record)
    assert re.match(
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[WARNING\] "
        r"\[isaacteleop\.test_line_format\] \[pid:\d+\] hello$",
        line,
    ), line


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: uids")
def test_log_dir_defaults_to_per_user_tmp(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    assert logging_config.log_dir() == Path(f"/tmp/isaacteleop-{os.getuid()}/logs")


@pytest.mark.skipif(os.name == "posix", reason="Covers the non-POSIX fallback")
def test_log_dir_defaults_to_the_platform_temp_dir(monkeypatch):
    """No uid to name a directory after, and none needed: the platform's own
    temp directory is already per-user, which is what the uid suffix buys
    on POSIX.
    """
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    default = logging_config.log_dir()
    assert default == Path(tempfile.gettempdir()) / "isaacteleop" / "logs"


def test_log_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    assert logging_config.log_dir() == tmp_path


def test_log_dir_honors_env_override_with_tilde(monkeypatch, tmp_path):
    """Python expands ``~``; the C++ side (sink_config.cpp's log_dir()) does
    not -- a real, documented-nowhere cross-language divergence. This pins the
    Python half; there is no test on the C++ side that could assert the
    opposite without contradicting this one, so the divergence has to be
    read off the two source files rather than a shared assertion.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", "~/logs")
    assert logging_config.log_dir() == tmp_path / "logs"


def test_log_dir_empty_override_falls_back_to_default(monkeypatch):
    """Python's ``os.environ.get(...) or default`` treats an empty string as
    unset; the C++ side (sink_config.cpp's log_dir()) only checks for a null
    pointer, so an empty ``ISAACTELEOP_LOG_DIR`` is honoured there as a literal
    empty path. Same divergence class as the tilde case above.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", "")
    monkeypatch.setenv("HOME", "/nonexistent-marker-for-this-test")
    assert logging_config.log_dir() != Path("")


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: mode bits")
def test_ensure_log_dir_is_owner_only(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    created = _core.ensure_log_dir()
    assert created == target
    assert stat.S_IMODE(created.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: mode bits")
def test_every_created_component_is_owner_only(monkeypatch, tmp_path):
    """Not just the leaf. The default log directory is <runtime dir>/logs, so a
    parents=True create that only chmods the leaf leaves the directory the log
    socket lives in at whatever the umask gave it.
    """
    target = tmp_path / "outer" / "inner" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    _core.ensure_log_dir()
    for created in (target, target.parent, target.parent.parent):
        assert stat.S_IMODE(created.stat().st_mode) == 0o700, created


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: mode bits")
def test_a_directory_we_did_not_create_keeps_its_permissions(monkeypatch, tmp_path):
    """An operator who points ISAACTELEOP_LOG_DIR at a directory they set up
    keeps the permissions they chose.
    """
    tmp_path.chmod(0o755)
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    _core.ensure_log_dir()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


@pytest.mark.skipif(os.name == "posix", reason="Covers the non-POSIX fallback")
def test_ensure_log_dir_creates_the_directory_without_mode_bits(monkeypatch, tmp_path):
    """Still created, just without the chmod and ownership check: neither has
    meaning where mode bits are advisory and st_uid is always 0.
    """
    target = tmp_path / "nested" / "logs"
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(target))
    created = _core.ensure_log_dir()
    assert created == target
    assert created.is_dir()


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only: uids")
def test_ensure_log_dir_refuses_a_directory_owned_by_someone_else(
    monkeypatch, tmp_path
):
    """A /tmp directory another user got to first is how a symlink gets planted."""
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    # Resolved before patching: the lambda must not call the name it replaces.
    other_uid = os.getuid() + 1
    monkeypatch.setattr(_core.os, "getuid", lambda: other_uid)
    with pytest.raises(PermissionError, match=str(other_uid)):
        _core.ensure_log_dir()
