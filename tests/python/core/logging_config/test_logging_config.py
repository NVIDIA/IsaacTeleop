# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for isaacteleop.logging_config."""

import io
import logging

import pytest
from isaacteleop import logging_config


@pytest.fixture(autouse=True)
def _restore_console_state():
    """Snapshot/restore the module-global console handler state around each test."""
    handler = logging_config._ensure_console_handler()
    saved_level = handler.level
    saved_filters = list(handler.filters)
    saved_console_filter = logging_config._console_filter
    yield
    handler.setLevel(saved_level)
    for f in list(handler.filters):
        handler.removeFilter(f)
    for f in saved_filters:
        handler.addFilter(f)
    logging_config._console_filter = saved_console_filter


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
    assert logging_config.get_logger("isaacteleop.foo") is logging.getLogger("isaacteleop.foo")


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
