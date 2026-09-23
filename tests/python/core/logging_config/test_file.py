# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The rotating log file: whose it is, and what survives a rotation."""

from __future__ import annotations

import logging
import stat
import threading

import pytest
from conftest import read_all

from isaaccapture.logging_config import _core
from isaaccapture.logging_config._file import _PrivateRotatingFileHandler


def make_handler(path, **kwargs):
    handler = _PrivateRotatingFileHandler(path, encoding="utf-8", **kwargs)
    handler.setFormatter(
        logging.Formatter(_core.LINE_FORMAT, datefmt=_core.DATE_FORMAT)
    )
    return handler


def test_creates_the_file_owner_only(tmp_path):
    path = tmp_path / "session.log"
    handler = make_handler(path)
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        handler.close()


def test_refuses_a_name_that_already_exists(tmp_path):
    # The name is guessable -- a timestamp to the second and a readable pid --
    # and ISAACCAPTURE_LOG_DIR may be a directory the operator shares.
    path = tmp_path / "session.log"
    path.write_text("someone else's\n")
    with pytest.raises(FileExistsError):
        make_handler(path)
    assert path.read_text() == "someone else's\n"


def test_refuses_a_symlink_and_leaves_its_target_alone(tmp_path):
    target = tmp_path / "victim"
    target.write_text("precious\n")
    link = tmp_path / "session.log"
    link.symlink_to(target)

    with pytest.raises(OSError):
        make_handler(link)
    assert target.read_text() == "precious\n"


def test_rotation_keeps_every_record_written_by_concurrent_threads(tmp_path):
    workers, per_worker = 8, 50
    handler = make_handler(tmp_path / "session.log", maxBytes=16384, backupCount=5)
    logger = logging.getLogger("isaaccapture.test.rotation")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # keep 400 records out of this process's own log

    start = threading.Barrier(workers)

    def emit(worker: int) -> None:
        start.wait()
        for index in range(per_worker):
            logger.info("worker %d record %03d", worker, index)

    threads = [threading.Thread(target=emit, args=(w,)) for w in range(workers)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            assert not thread.is_alive()
    finally:
        handler.close()
        logger.removeHandler(handler)
        logger.propagate = True

    files = sorted(tmp_path.iterdir())
    assert len(files) > 1, "the run was too small to rotate at all"
    assert all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)

    produced = read_all(files)
    missing = [
        f"worker {w} record {i:03d}"
        for w in range(workers)
        for i in range(per_worker)
        if f"worker {w} record {i:03d}" not in produced
    ]
    assert missing == []
