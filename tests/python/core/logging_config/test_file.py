# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._file: the one rotating file handler,
always DEBUG and below, independent of the console's own level."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _core, _file

pytestmark = pytest.mark.usefixtures("_restore_console_state")


def test_file_handler_attaches_once():
    root = logging.getLogger(_core.ROOT_LOGGER_NAME)
    handler = _file.ensure_handler()
    assert handler in root.handlers
    assert _file.ensure_handler() is handler
    assert root.handlers.count(handler) == 1


def test_file_handler_is_always_debug_level():
    assert _file.ensure_handler().level == logging.DEBUG


def test_file_handler_filename_includes_pid():
    handler = _file.ensure_handler()
    assert f".{os.getpid()}.log" in handler.baseFilename


def test_file_handler_filename_includes_timestamp():
    handler = _file.ensure_handler()
    name = Path(handler.baseFilename).name
    assert re.fullmatch(rf"\d{{8}}-\d{{6}}\.isaacteleop\.{os.getpid()}\.log", name), (
        name
    )


def test_file_handler_captures_debug_regardless_of_console_level():
    """The file is the full record even when the console is set well above DEBUG."""
    logger = logging.getLogger("isaacteleop.test_file_handler_captures_debug")
    logging_config.set_console_level("error")
    handler = _file.ensure_handler()
    marker = "unique-marker-for-file-debug-capture-test"

    logger.debug(marker)
    handler.flush()

    assert marker in Path(handler.baseFilename).read_text(encoding="utf-8")


def test_console_keyword_filter_does_not_touch_the_file_handler():
    """set_console_filter() narrows the console handler only; the file is
    still the full, unfiltered record of the session.
    """
    logger = logging.getLogger("isaacteleop.test_file_ignores_console_filter")
    logging_config.set_console_filter("something-else-entirely")
    try:
        handler = _file.ensure_handler()
        marker = "unfiltered-by-the-console-keyword-filter"
        logger.debug(marker)
        handler.flush()
        assert marker in Path(handler.baseFilename).read_text(encoding="utf-8")
    finally:
        logging_config.set_console_filter(None)


def test_rotation_bounds_are_10mib_times_5_backups():
    """Mutation-verified: deleting the maxBytes/backupCount arguments from
    ensure_handler()'s RotatingFileHandler constructor would leave the suite
    green if this were absent -- nothing else exercises rotation.
    """
    handler = _file.ensure_handler()
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_file_is_written_as_utf8():
    """Mutation-verified: swapping the handler's encoding to ascii leaves the
    suite green unless a non-ASCII message is actually logged and read back.
    """
    logger = logging.getLogger("isaacteleop.test_file_utf8")
    handler = _file.ensure_handler()
    marker = "utf8-marker-éè中文"
    logger.debug(marker)
    handler.flush()
    assert marker in Path(handler.baseFilename).read_text(encoding="utf-8")


def test_file_line_format_matches_line_format():
    """Mutation-verified: replacing the handler's formatter with
    ``logging.Formatter("%(message)s")`` leaves the suite green, since every
    other test here only ever greps for a marker substring.
    """
    logger = logging.getLogger("isaacteleop.test_file_line_format")
    handler = _file.ensure_handler()
    marker = "line-format-marker"
    logger.warning(marker)
    handler.flush()
    lines = [
        line
        for line in Path(handler.baseFilename).read_text(encoding="utf-8").splitlines()
        if marker in line
    ]
    assert len(lines) == 1, lines
    assert re.match(
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[WARNING\] "
        rf"\[isaacteleop\.test_file_line_format\] \[pid:{os.getpid()}\] {marker}$",
        lines[0],
    ), lines[0]
