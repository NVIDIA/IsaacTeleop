# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capture of raw fd 1 / fd 2 writes -- the output no logger can reach.

Every case runs in a child process. A descriptor is process-wide, and pytest is
reading this process's fd 1 and fd 2 for its own report; a scope entered here
would move them out from under it.
"""

from __future__ import annotations

import json

from conftest import capture_logs, clean_env, read, read_all, run_python, session_logs

_PREAMBLE = """
import json, logging, os, subprocess, sys, threading
from isaaccapture.logging_config import _native_api
report = {}

def save():
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(report, handle)
"""


def run_child(tmp_path, body: str, **overrides):
    log_dir = tmp_path / "child-logs"
    log_dir.mkdir(exist_ok=True)
    report_path = tmp_path / "report.json"
    result = run_python(
        _PREAMBLE + body + "\nsave()\n",
        clean_env(log_dir, **overrides),
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return result, log_dir, report


def captured(log_dir) -> str:
    return read_all(capture_logs(log_dir))


def test_raw_writes_are_captured_only_inside_the_scope(tmp_path):
    result, log_dir, _ = run_child(
        tmp_path,
        """
os.write(2, b"before the scope\\n")
with _native_api.capture_native_output() as path:
    report["path"] = str(path)
    os.write(1, b"vendor on fd1\\n")
    os.write(2, b"vendor on fd2\\n")
    print("python stdout stays put")
    print("python stderr stays put", file=sys.stderr)
os.write(2, b"after the scope\\n")
""",
    )

    inside = captured(log_dir)
    assert "vendor on fd1" in inside
    assert "vendor on fd2" in inside
    # Outside a scope isaaccapture does not touch the host's descriptors at all.
    assert "before the scope" not in inside
    assert "after the scope" not in inside
    assert "before the scope" in result.stderr
    assert "after the scope" in result.stderr

    # Python-level writes are exempt: the stream objects move onto duplicates.
    assert "python stdout stays put" in result.stdout
    assert "python stderr stays put" in result.stderr
    assert "python stdout stays put" not in inside


def test_nested_scopes_restore_at_the_outermost_exit(tmp_path):
    result, log_dir, _ = run_child(
        tmp_path,
        """
with _native_api.capture_native_output():
    os.write(2, b"outer\\n")
    with _native_api.capture_native_output():
        os.write(2, b"inner\\n")
    os.write(2, b"between\\n")
os.write(2, b"outside\\n")
""",
    )

    inside = captured(log_dir)
    assert "outer" in inside and "inner" in inside and "between" in inside
    assert "outside" not in inside
    assert "outside" in result.stderr


def test_concurrent_scopes_leave_the_descriptors_as_they_were(tmp_path):
    result, log_dir, report = run_child(
        tmp_path,
        """
log = logging.getLogger("isaaccapture.test.capture")
before = [os.fstat(fd) for fd in (1, 2)]
start = threading.Barrier(8)

def scoper():
    start.wait()
    for _ in range(25):
        with _native_api.capture_native_output():
            os.write(1, b"vendor line\\n")

def emitter(index):
    start.wait()
    for record in range(25):
        log.warning("thread %d record %02d", index, record)

threads = [threading.Thread(target=scoper) for _ in range(4)]
threads += [threading.Thread(target=emitter, args=(i,)) for i in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=120)
    report["alive"] = report.get("alive", False) or thread.is_alive()

after = [os.fstat(fd) for fd in (1, 2)]
report["restored"] = [
    (b.st_dev, b.st_ino) == (a.st_dev, a.st_ino) for b, a in zip(before, after)
]
""",
    )

    assert report["alive"] is False
    assert report["restored"] == [True, True]
    assert "vendor line" in captured(log_dir)

    # Nothing a logger produced was lost to a scope opening underneath it. The
    # rotating file is unconditional; the console copy of a record emitted in
    # the instant _begin rebinds fd 2 but has not yet moved the handler's stream
    # lands in the capture file instead of the terminal, so the two are checked
    # together rather than pretending the split is deterministic.
    expected = [f"thread {t} record {r:02d}" for t in range(4) for r in range(25)]
    logged = read_all(session_logs(log_dir))
    terminal = result.stderr + captured(log_dir)
    assert [line for line in expected if line not in logged] == []
    assert [line for line in expected if line not in terminal] == []


def test_a_warning_inside_a_scope_still_reaches_the_terminal(tmp_path):
    # The console handler is moved onto a duplicate of the real fd 2, so an
    # operator watching a native bring-up still sees what went wrong.
    result, log_dir, _ = run_child(
        tmp_path,
        """
log = logging.getLogger("isaaccapture.test.capture.console")
with _native_api.capture_native_output():
    log.warning("openxr instance creation failed")
    os.write(2, b"vendor noise\\n")
""",
    )

    assert "openxr instance creation failed" in result.stderr
    assert "openxr instance creation failed" in read_all(session_logs(log_dir))
    inside = captured(log_dir)
    assert "vendor noise" in inside
    assert "openxr instance creation failed" not in inside


def test_capture_off_leaves_the_descriptors_alone_but_still_publishes_the_file(
    tmp_path,
):
    # The switch governs the host's descriptors; a process isaaccapture launches
    # is not the host, and still needs the path.
    result, log_dir, report = run_child(
        tmp_path,
        """
with _native_api.capture_native_output() as path:
    report["path"] = None if path is None else str(path)
    os.write(2, b"not captured\\n")
report["published"] = os.environ.get("ISAACCAPTURE_NATIVE_CAPTURE_FILE")
report["fd"] = _native_api.native_capture_fd() is not None
""",
        ISAACCAPTURE_NATIVE_CAPTURE="off",
    )

    assert report["path"] is None
    assert report["published"] is not None
    assert report["fd"] is True
    assert "not captured" in result.stderr
    assert captured(log_dir) == ""


def test_a_capture_file_nothing_wrote_to_is_removed_at_exit(tmp_path):
    # Most processes that import isaaccapture emit no raw fd output at all, and
    # the file has to exist before the first byte can land in it.
    _, log_dir, report = run_child(
        tmp_path,
        """
report["path"] = str(_native_api.native_capture_path())
report["existed"] = os.path.isfile(report["path"])
""",
    )

    assert report["existed"] is True
    assert capture_logs(log_dir) == []


def test_a_child_given_the_capture_fd_writes_into_it(tmp_path):
    result, log_dir, report = run_child(
        tmp_path,
        """
fd = _native_api.native_capture_fd()
report["fd"] = fd
subprocess.run(
    [sys.executable, "-c", "print('grandchild on stdout')"], stdout=fd, check=True
)
""",
    )

    assert report["fd"] is not None
    # No scope was open: pointing a launched process's descriptors at the file
    # is how out-of-process vendor output is kept off the host's terminal.
    assert "grandchild on stdout" in captured(log_dir)
    assert "grandchild on stdout" not in result.stdout


def test_the_capture_file_is_owner_only(tmp_path):
    _, log_dir, _ = run_child(
        tmp_path,
        """
with _native_api.capture_native_output():
    os.write(2, b"vendor noise\\n")
""",
    )

    files = capture_logs(log_dir)
    assert len(files) == 1
    assert oct(files[0].stat().st_mode)[-3:] == "600"
    assert "vendor noise" in read(files[0])
