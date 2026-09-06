# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for isaacteleop.logging_config."""

import io
import logging
import os
from pathlib import Path

import pytest
from isaacteleop import logging_config


@pytest.fixture(autouse=True)
def _restore_console_state():
    """Snapshot/restore the module-global console handler state around each test."""
    handler = logging_config._ensure_console_handler()
    saved_level = handler.level
    saved_filters = list(handler.filters)
    saved_console_filter = logging_config._console_filter
    saved_filter_pattern = logging_config._filter_pattern
    saved_filter_target = logging_config._filter_target
    yield
    handler.setLevel(saved_level)
    for f in list(handler.filters):
        handler.removeFilter(f)
    for f in saved_filters:
        handler.addFilter(f)
    logging_config._console_filter = saved_console_filter
    logging_config._filter_pattern = saved_filter_pattern
    logging_config._filter_target = saved_filter_target


def test_console_handler_attaches_once():
    root = logging.getLogger(logging_config.ROOT_LOGGER_NAME)
    handler = logging_config._ensure_console_handler()
    assert handler in root.handlers
    assert logging_config._ensure_console_handler() is handler
    assert root.handlers.count(handler) == 1


def test_set_console_level_by_name_and_int():
    logging_config.set_console_level("warning")
    assert logging_config._ensure_console_handler().level == logging.WARNING
    logging_config.set_console_level(logging.INFO)
    assert logging_config._ensure_console_handler().level == logging.INFO


def test_set_console_level_rejects_unknown_name():
    with pytest.raises(ValueError):
        logging_config.set_console_level("nope")


def _record(name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, None, None)


def test_keyword_filter_matches_logger_name():
    f = logging_config.KeywordFilter("manus", target="logger_name")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert not f.filter(_record("isaacteleop.oxr", "hello"))


def test_keyword_filter_matches_content():
    f = logging_config.KeywordFilter("dongle", target="content")
    assert f.filter(_record("isaacteleop.x", "Connected to dongle 0"))
    assert not f.filter(_record("isaacteleop.x", "unrelated"))


def test_keyword_filter_both_target_matches_either():
    f = logging_config.KeywordFilter("manus", target="both")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert f.filter(_record("isaacteleop.x", "manus glove connected"))
    assert not f.filter(_record("isaacteleop.x", "hello"))


def test_keyword_filter_rejects_unknown_target():
    with pytest.raises(ValueError):
        logging_config.KeywordFilter("manus", target="nope")


def test_set_console_filter_applies_and_clears():
    logging_config.set_console_filter("manus")
    handler = logging_config._ensure_console_handler()
    assert logging_config._console_filter in handler.filters
    logging_config.set_console_filter(None)
    assert logging_config._console_filter is None


def test_get_logger_without_cls_matches_plain_getlogger():
    assert logging_config.get_logger("isaacteleop.foo") is logging.getLogger(
        "isaacteleop.foo"
    )


def test_get_logger_with_cls_suffixes_class_name():
    class SomeClass:
        pass

    logger = logging_config.get_logger("isaacteleop.foo", cls=SomeClass)
    assert logger.name == "isaacteleop.foo.SomeClass"


def test_console_handler_end_to_end_level_filtering():
    """A record below the console level must not reach the handler's stream."""
    logger = logging.getLogger("isaacteleop.test_console_handler_end_to_end")
    logging_config.set_console_level("info")

    handler = logging_config._ensure_console_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.debug("should not appear")
        logger.info("should appear")
    finally:
        handler.stream = original_stream

    assert "should not appear" not in stream.getvalue()
    assert "should appear" in stream.getvalue()


def test_log_dir_defaults_to_dot_isaacteleop(monkeypatch):
    monkeypatch.delenv("ISAACTELEOP_LOG_DIR", raising=False)
    assert logging_config._log_dir() == logging_config.DEFAULT_LOG_DIR


def test_log_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ISAACTELEOP_LOG_DIR", str(tmp_path))
    assert logging_config._log_dir() == tmp_path


def test_file_handler_attaches_once():
    root = logging.getLogger(logging_config.ROOT_LOGGER_NAME)
    handler = logging_config._ensure_file_handler()
    assert handler in root.handlers
    assert logging_config._ensure_file_handler() is handler
    assert root.handlers.count(handler) == 1


def test_file_handler_is_always_debug_level():
    assert logging_config._ensure_file_handler().level == logging.DEBUG


def test_file_handler_filename_includes_pid():
    handler = logging_config._ensure_file_handler()
    assert f".{os.getpid()}.log" in handler.baseFilename


def test_file_handler_captures_debug_regardless_of_console_level():
    """The file is the full record even when the console is set well above DEBUG."""
    logger = logging.getLogger("isaacteleop.test_file_handler_captures_debug")
    logging_config.set_console_level("error")
    handler = logging_config._ensure_file_handler()
    marker = "unique-marker-for-file-debug-capture-test"

    logger.debug(marker)
    handler.flush()

    assert marker in Path(handler.baseFilename).read_text(encoding="utf-8")


def test_trace_level_value_and_name():
    assert logging_config.TRACE == 5
    assert logging.getLevelName(5) == "TRACE"


def test_trace_method_exists_and_is_callable():
    logger = logging.getLogger("isaacteleop.test_trace_method")
    logger.trace("a trace message, level=%s", "trace")  # must not raise


def test_trace_is_below_debug_and_filtered_by_default():
    logger = logging.getLogger("isaacteleop.test_trace_filtering")
    logging_config.set_console_level("debug")  # still above TRACE
    handler = logging_config._ensure_console_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.trace("should not appear")
        logger.debug("should appear")
    finally:
        handler.stream = original_stream

    assert "should not appear" not in stream.getvalue()
    assert "should appear" in stream.getvalue()


def test_trace_visible_once_console_level_lowered_to_trace():
    logger = logging.getLogger("isaacteleop.test_trace_opt_in")
    logging_config.set_console_level("trace")
    handler = logging_config._ensure_console_handler()
    stream = io.StringIO()
    original_stream = handler.stream
    handler.stream = stream
    try:
        logger.trace("now visible")
    finally:
        handler.stream = original_stream

    assert "now visible" in stream.getvalue()


def test_configure_level_only_does_not_touch_filter():
    logging_config.set_console_filter("existing")
    logging_config.configure(level="warning")
    assert logging_config._ensure_console_handler().level == logging.WARNING
    assert logging_config._filter_pattern == "existing"


def test_configure_partial_overlay_preserves_filter_across_calls():
    """The exact two-call sequence from the design doc's section 12, Step 8."""
    logging_config.configure(filter="manus")
    assert logging_config._filter_pattern == "manus"

    logging_config.configure(level="debug")
    assert logging_config._ensure_console_handler().level == logging.DEBUG
    assert logging_config._filter_pattern == "manus"  # not cleared by the second call


def test_configure_explicit_none_clears_filter():
    logging_config.configure(filter="manus")
    assert logging_config._filter_pattern == "manus"

    logging_config.configure(filter=None)
    assert logging_config._filter_pattern is None
    assert logging_config._console_filter is None


def test_configure_filter_target_alone_preserves_pattern():
    logging_config.configure(filter="manus", filter_target="logger_name")
    logging_config.configure(filter_target="content")
    assert logging_config._filter_pattern == "manus"
    assert logging_config._filter_target == "content"


def test_configure_with_no_arguments_is_a_no_op():
    logging_config.set_console_level("warning")
    logging_config.set_console_filter("existing")
    logging_config.configure()
    assert logging_config._ensure_console_handler().level == logging.WARNING
    assert logging_config._filter_pattern == "existing"
