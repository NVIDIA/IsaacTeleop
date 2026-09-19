# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared markers and state hygiene for every file in this leaf.

Every module here imports ``isaacteleop.logging_config``'s private submodules
directly (``_console``, ``_core``, ``_file``, ``_forwarding``, ``_native_fd``),
because most of what this leaf pins is internal state, not just the public
API. That state is module-global and shared by the whole process, so an
autouse fixture here winds back the pieces every file can perturb, rather
than each file doing it separately and risking drift.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from isaacteleop.logging_config import _console, _native_fd

# logging_config deliberately degrades where the POSIX facilities it is built on
# are missing: no uid in the default log directory, no 0700 chmod, no ownership
# check, and no Unix-socket forwarding at all. Assertions that only hold on POSIX
# carry this marker; the degraded behaviour is asserted separately rather than
# left unchecked, so the platform the Windows CI job builds for is covered in
# both directions.
#
# The condition is re-derived from os.name rather than read off _core._POSIX: a
# test that reuses the constant under test can only ever agree with it.
_POSIX = os.name == "posix"
_posix_only = pytest.mark.skipif(
    not _POSIX, reason="POSIX-only: uids, mode bits and Unix domain sockets"
)
_non_posix_only = pytest.mark.skipif(
    _POSIX, reason="Covers the fallback taken where POSIX facilities are absent"
)

# log_bridge_emit_record, built by tests/cpp/core/log_bridge/CMakeLists.txt and
# handed over by this leaf's own CMakeLists.txt. It logs one record through
# isaacteleop::Logger and exits, which is the only way to put a real C++ sender
# at the other end of the socket. Absent when this file is run straight from a
# source checkout with no build directory, hence a skip rather than a failure.
_CPP_EMITTER = os.environ.get("ISAACTELEOP_LOG_EMITTER")
_needs_cpp_emitter = pytest.mark.skipif(
    not _CPP_EMITTER,
    reason="needs the CMake-built log_bridge_emit_record (ISAACTELEOP_LOG_EMITTER)",
)


@pytest.fixture
def _short_socket_dir():
    """A private path short enough for every POSIX sockaddr_un.sun_path."""
    with tempfile.TemporaryDirectory(prefix="it-log-", dir="/tmp") as directory:
        yield Path(directory)


@pytest.fixture(autouse=True)
def _restore_console_state():
    """Snapshot/restore the module-global console handler state around each test."""
    handler = _console.ensure_handler()
    saved_level = handler.level
    saved_filters = list(handler.filters)
    saved_active_filter = _console._active_filter
    saved_native_echo = _native_fd._echo
    saved_env_level = os.environ.get("ISAACTELEOP_LOG_LEVEL")
    try:
        yield
    finally:
        handler.setLevel(saved_level)
        for f in list(handler.filters):
            handler.removeFilter(f)
        for f in saved_filters:
            handler.addFilter(f)
        _console._active_filter = saved_active_filter
        _native_fd._echo = saved_native_echo
        if saved_env_level is None:
            os.environ.pop("ISAACTELEOP_LOG_LEVEL", None)
        else:
            os.environ["ISAACTELEOP_LOG_LEVEL"] = saved_env_level
