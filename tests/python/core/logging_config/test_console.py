# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for isaacteleop.logging_config._console: the one console handler,
its level/filter/colour controls, and the ANSI colouring itself."""

from __future__ import annotations

import io
import logging
import os
import sys

import pytest
from isaacteleop import logging_config
from isaacteleop.logging_config import _console, _core

pytestmark = pytest.mark.usefixtures("_restore_console_state")


def test_console_handler_attaches_once():
    root = logging.getLogger(_core.ROOT_LOGGER_NAME)
    handler = _console.ensure_handler()
    assert handler in root.handlers
    assert _console.ensure_handler() is handler
    assert root.handlers.count(handler) == 1


def test_console_handler_defaults_to_info():
    """The out-of-the-box verbosity: nothing has called set_console_level()."""
    assert _console.ensure_handler().level == logging.INFO


def test_console_handler_writes_stderr_not_stdout():
    """StreamHandler's own default, but load-bearing here: capture_native_output()
    only ever moves duplicates onto sys.stdout/sys.stderr, and picking the wrong
    one would silently stop tracking which descriptor the handler follows.
    """
    assert _console.ensure_handler().stream is sys.stderr


def test_set_console_level_by_name_and_int():
    logging_config.set_console_level("warning")
    assert _console.ensure_handler().level == logging.WARNING
    logging_config.set_console_level(logging.INFO)
    assert _console.ensure_handler().level == logging.INFO


def test_set_console_level_rejects_unknown_name():
    with pytest.raises(ValueError):
        logging_config.set_console_level("nope")


def test_set_console_level_does_not_touch_filter():
    logging_config.set_console_filter("existing")
    active = _console._active_filter
    logging_config.set_console_level("warning")
    assert _console.ensure_handler().level == logging.WARNING
    assert _console._active_filter is active
    assert active in _console.ensure_handler().filters


def test_set_console_level_exports_it_for_forked_processes(monkeypatch):
    """A fork+exec'd plugin or a standalone C++ process has no Python console
    handler of its own; ISAACTELEOP_LOG_LEVEL is how it learns the leader's
    current threshold (sink_config.cpp's console_level() reads the same
    variable, with the same name-to-level table).
    """
    monkeypatch.delenv("ISAACTELEOP_LOG_LEVEL", raising=False)
    logging_config.set_console_level("warning")
    assert os.environ["ISAACTELEOP_LOG_LEVEL"] == "warning"


def test_an_unnamed_int_level_leaves_the_exported_variable_stale(monkeypatch):
    """25 has no name in _LEVEL_NAMES, so nothing can be written for it -- and
    nothing is: the variable keeps whatever a prior named level set, which a
    process reading it later will wrongly treat as still current.
    """
    monkeypatch.setenv("ISAACTELEOP_LOG_LEVEL", "warning")
    logging_config.set_console_level(25)
    assert _console.ensure_handler().level == 25
    assert os.environ["ISAACTELEOP_LOG_LEVEL"] == "warning"


def _record(name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, None, None)


def test_keyword_filter_matches_logger_name():
    f = _console.KeywordFilter("manus", target="logger_name")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert not f.filter(_record("isaacteleop.oxr", "hello"))


def test_keyword_filter_matches_content():
    f = _console.KeywordFilter("dongle", target="content")
    assert f.filter(_record("isaacteleop.x", "Connected to dongle 0"))
    assert not f.filter(_record("isaacteleop.x", "unrelated"))


def test_keyword_filter_both_target_matches_either():
    f = _console.KeywordFilter("manus", target="both")
    assert f.filter(_record("isaacteleop.plugins.manus", "hello"))
    assert f.filter(_record("isaacteleop.x", "manus glove connected"))
    assert not f.filter(_record("isaacteleop.x", "hello"))


def test_keyword_filter_rejects_unknown_target():
    with pytest.raises(ValueError):
        _console.KeywordFilter("manus", target="nope")


def test_keyword_filter_pattern_is_a_real_regex():
    """The public contract is a pattern, not a literal substring -- ``in`` would
    pass every existing test here too, since none of them needed the difference.
    """
    f = _console.KeywordFilter(r"dongle \d+", target="content")
    assert f.filter(_record("isaacteleop.x", "Connected to dongle 0"))
    assert not f.filter(_record("isaacteleop.x", "dongle without a number"))


def test_set_console_filter_applies_and_clears():
    logging_config.set_console_filter("manus")
    handler = _console.ensure_handler()
    assert _console._active_filter in handler.filters
    logging_config.set_console_filter(None)
    assert _console._active_filter is None
    # Not just the module global: the clear must reach the handler's own
    # filter list, or a record the old filter would have dropped keeps
    # being dropped by a filter object nothing external can see anymore.
    assert not handler.filters


def test_set_console_filter_replaces_rather_than_accumulates():
    logging_config.set_console_filter("first")
    logging_config.set_console_filter("second")
    handler = _console.ensure_handler()
    assert len(handler.filters) == 1
    assert handler.filters[0] is _console._active_filter
    logging_config.set_console_filter(None)


def test_console_handler_end_to_end_level_filtering():
    """A record below the console level must not reach the handler's stream."""
    logger = logging.getLogger("isaacteleop.test_console_handler_end_to_end")
    logging_config.set_console_level("info")

    handler = _console.ensure_handler()
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


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, which is what gates the colouring."""

    def isatty(self) -> bool:
        return True


def _render(level: int, name: str, *, tty: bool = True) -> str:
    handler = _console.ensure_handler()
    original = handler.stream
    handler.stream = _Tty() if tty else io.StringIO()
    try:
        logging.getLogger(name).log(level, "message")
        return handler.stream.getvalue()
    finally:
        handler.stream = original


def test_warning_is_yellow_and_error_is_red():
    assert _render(logging.WARNING, "isaacteleop.t.warn").startswith("\033[33m")
    assert _render(logging.ERROR, "isaacteleop.t.err").startswith("\033[31m")
    # Above ERROR too: compared with >=, so a level between the stdlib's lands
    # on the right side rather than falling through uncoloured.
    assert _render(logging.CRITICAL, "isaacteleop.t.crit").startswith("\033[31m")


def test_levels_below_warning_are_left_plain():
    """Colour only helps if the ordinary case is not coloured."""
    logging_config.set_console_level("trace")
    for level in (logging_config.TRACE, logging.DEBUG, logging.INFO):
        assert "\033[" not in _render(level, "isaacteleop.t.quiet")


def test_a_line_with_no_level_colour_at_all_is_returned_unmodified():
    """Neither a level colour (below WARNING) nor an emphasis colour (none
    registered) applies, so format() must take its very first branch and
    return the plain, unmodified line -- no escape codes anywhere.
    """
    line = _render(logging.INFO, "isaacteleop.t.plain")
    assert "\033[" not in line


def test_emphasis_without_a_level_colour_still_resumes_the_ansi_default():
    """An emphasis colour on a sub-WARNING logger has no level colour to hand
    back to, so it must resume the plain ANSI default (mid-line, right after
    the name field) rather than a level colour that was never applied -- and,
    because there is still no level colour, the line as a whole is not
    wrapped in an opening/closing escape the way an ERROR line would be.
    """
    name = "isaacteleop.t.emphasis_no_level"
    logging_config.set_logger_colors({name: "\033[36m"})
    try:
        line = _render(logging.INFO, name)
    finally:
        logging_config.set_logger_colors({name: None})
    assert not line.startswith("\033[31m")
    assert not line.startswith("\033[33m")
    assert f"\033[36m{name}\033[0m" in line
    # Not wrapped: the trailing reset the name field already carries is the
    # only escape code in the line.
    assert line.rstrip("\n").count("\033[0m") == 1


def test_logger_emphasis_resumes_the_level_colour():
    """The pid and the message belong to the same record as the name, so the
    name's colour must hand back to the level's rather than to the default.
    """
    name = "isaacteleop.t.emphasis"
    logging_config.set_logger_colors({name: "\033[36m"})
    try:
        line = _render(logging.ERROR, name)
    finally:
        logging_config.set_logger_colors({name: None})

    assert line.startswith("\033[31m")
    assert f"\033[36m{name}\033[31m" in line
    assert line.rstrip("\n").endswith("\033[0m")


def test_logger_colors_match_exact_name_not_prefix():
    """The most natural way to misuse this API: registering the parent name
    and expecting every child logger to inherit the colour.
    """
    logging_config.set_logger_colors({"isaacteleop.t.exact": "\033[36m"})
    try:
        parent_line = _render(logging.ERROR, "isaacteleop.t.exact")
        child_line = _render(logging.ERROR, "isaacteleop.t.exact.child")
    finally:
        logging_config.set_logger_colors({"isaacteleop.t.exact": None})
    assert "\033[36m" in parent_line
    assert "\033[36m" not in child_line


def test_logger_colors_are_additive_not_a_whole_table_replacement():
    logging_config.set_logger_colors({"isaacteleop.t.first": "\033[36m"})
    try:
        logging_config.set_logger_colors({"isaacteleop.t.second": "\033[35m"})
        try:
            assert "\033[36m" in _render(logging.ERROR, "isaacteleop.t.first")
            assert "\033[35m" in _render(logging.ERROR, "isaacteleop.t.second")
        finally:
            logging_config.set_logger_colors({"isaacteleop.t.second": None})
    finally:
        logging_config.set_logger_colors({"isaacteleop.t.first": None})


def test_logger_colors_none_revokes_a_registered_colour():
    name = "isaacteleop.t.revoke"
    logging_config.set_logger_colors({name: "\033[36m"})
    logging_config.set_logger_colors({name: None})
    assert "\033[36m" not in _render(logging.ERROR, name)


def test_set_logger_colors_rejects_non_sgr_values():
    """A security-relevant gate, not a style nit: a registered value is written
    to the terminal raw, so anything outside an SGR escape -- a cursor move, an
    OSC sequence, a bare newline -- would be an injection vector.
    """
    with pytest.raises(ValueError):
        logging_config.set_logger_colors({"isaacteleop.t.bad": "red"})
    with pytest.raises(ValueError):
        logging_config.set_logger_colors({"isaacteleop.t.bad": "\033]0;evil\007"})


def test_nothing_is_coloured_when_the_stream_is_not_a_terminal():
    """A pipe, a CI log or a redirected file would only get escape noise -- and
    anything parsing the output would get it too.
    """
    name = "isaacteleop.t.pipe"
    logging_config.set_logger_colors({name: "\033[36m"})
    try:
        assert "\033[" not in _render(logging.ERROR, name, tty=False)
    finally:
        logging_config.set_logger_colors({name: None})


@pytest.mark.parametrize(
    "stream", [None, io.StringIO()], ids=["none", "detached-or-closed"]
)
def test_a_stream_that_cannot_answer_isatty_is_treated_as_not_a_terminal(stream):
    """redirect_stdout(None) (a no-stdio interpreter) and a stream whose isatty()
    itself raises must both fall back to "not a terminal" rather than let the
    AttributeError/OSError/ValueError escape into the logging call site.
    """
    name = "isaacteleop.t.unanswerable"
    logging_config.set_logger_colors({name: "\033[36m"})
    handler = _console.ensure_handler()
    original = handler.stream
    if stream is not None:
        stream.close()  # a closed StringIO raises ValueError from isatty()
    handler.stream = stream
    try:
        logging.getLogger(name).error("message")  # must not raise
    finally:
        handler.stream = original
        logging_config.set_logger_colors({name: None})


def test_console_formatting_restores_the_record_name_for_the_next_handler():
    """The record object is shared across every handler on the logger: a name
    rewritten with colour for the console must be put back before the file
    handler -- attached to the same logger, formatting the same record -- ever
    sees it, or the file would carry a name with raw escape codes baked in.

    Proven end-to-end, not just by inspecting the record afterwards: a second,
    file-like handler is attached to the same logger, and its own rendered
    output is asserted to contain no escape codes at all.
    """
    name = "isaacteleop.t.shared"
    logging_config.set_logger_colors({name: "\033[36m"})
    logger = logging.getLogger(name)
    buffer = io.StringIO()
    file_like = logging.StreamHandler(buffer)
    file_like.setFormatter(
        logging.Formatter(_core.LINE_FORMAT, datefmt=_core.DATE_FORMAT)
    )
    logger.addHandler(file_like)
    try:
        logging.getLogger(name).error("message")
    finally:
        logger.removeHandler(file_like)
        logging_config.set_logger_colors({name: None})
    assert "\033[" not in buffer.getvalue()
    assert name in buffer.getvalue()
