# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make CloudXR python sources importable without installing ``isaacteleop``.

* Flat ``sys.path`` entry: ``from oob_teleop_hub import …`` (no relative imports).
* Synthetic package ``isaacteleop_py_test_ns.cloudxr``:
  ``from isaacteleop_py_test_ns.cloudxr.oob_teleop_env import …`` so modules that
  use relative imports load correctly.

The synthetic package has two levels because the real one does. A relative
import is resolved against the loaded module's ``__package__``, by dropping
``level - 1`` trailing components from it -- so ``from .. import x`` inside
``isaacteleop.cloudxr.wss`` reaches ``isaacteleop``, and the same line inside a
module loaded under a one-level package has nothing left to drop and raises
``attempted relative import beyond top-level package``. Mirroring the real
shape is what makes a module behave here exactly as it does in the package;
a flatter stand-in silently constrains what the source file is allowed to say.

The parent's ``__path__`` points at ``src/python/isaacteleop``, so a sibling
subpackage a cloudxr module reaches for -- ``logging_config`` today -- resolves
to the real source. Nothing executes ``isaacteleop/__init__.py``: these are
plain module objects carrying a ``__path__``, so the eager import list in that
file, and the compiled extensions it pulls in, stay out of the way.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import socket
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

_tests_python = Path(__file__).resolve().parents[2]
if str(_tests_python) not in sys.path:
    sys.path.insert(0, str(_tests_python))

from repo_paths import repo_root  # noqa: E402

_CLOUDXR_PY = repo_root() / "src" / "python" / "isaacteleop" / "cloudxr"
if _CLOUDXR_PY.is_dir() and str(_CLOUDXR_PY) not in sys.path:
    sys.path.insert(0, str(_CLOUDXR_PY))

ISAACTELEOP_TEST_PKG = "isaacteleop_py_test_ns"
CLOUDXR_TEST_PKG = f"{ISAACTELEOP_TEST_PKG}.cloudxr"


def _synthetic_package(name: str, source_dir: Path) -> types.ModuleType:
    """Register *name* as a package whose submodules come from *source_dir*.

    A module object with a ``__path__`` is all the import system needs to treat
    it as a package; the directory's own ``__init__.py`` is never run.
    """
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(source_dir)]
    sys.modules[name] = pkg
    parent, _, leaf = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], leaf, pkg)
    return pkg


def _ensure_cloudxr_package() -> None:
    if CLOUDXR_TEST_PKG in sys.modules:
        return
    _synthetic_package(ISAACTELEOP_TEST_PKG, _CLOUDXR_PY.parent)
    _synthetic_package(CLOUDXR_TEST_PKG, _CLOUDXR_PY)

    def load(mod: str) -> None:
        full = f"{CLOUDXR_TEST_PKG}.{mod}"
        path = _CLOUDXR_PY / f"{mod}.py"
        spec = importlib.util.spec_from_file_location(full, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
        setattr(sys.modules[CLOUDXR_TEST_PKG], mod, module)

    load("oob_teleop_hub")
    load("oob_teleop_env")
    load("oob_teleop_adb")
    load("webclient")


_ensure_cloudxr_package()


# ============================================================================
# Shared CloudXRService test doubles (used by test_service.py + test_launcher.py)
# ============================================================================


class FakeEnvConfig:
    """Minimal stand-in for EnvConfig."""

    def __init__(self, run_dir: str, logs_dir: Path) -> None:
        self._run_dir = run_dir
        self._logs_dir = logs_dir

    @classmethod
    def from_args(cls, install_dir, env_file=None):
        raise NotImplementedError("Should be patched")

    def openxr_run_dir(self) -> str:
        return self._run_dir

    def ensure_logs_dir(self) -> Path:
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        return self._logs_dir

    def env_filepath(self) -> str:
        return os.path.join(self._run_dir, "cloudxr.env")


@contextmanager
def live_ipc_socket(run_dir: str):
    """Serve ``run_dir``'s IPC socket for the duration of the block.

    Binds relative from a chdir: AF_UNIX ``sun_path`` caps at 108 bytes,
    which pytest's tmp_path can exceed.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cwd = os.getcwd()
    try:
        os.chdir(run_dir)
        with contextlib.suppress(FileNotFoundError):
            os.remove("ipc_cloudxr")
        sock.bind("ipc_cloudxr")
        sock.listen(1)
        yield sock
    finally:
        os.chdir(cwd)
        sock.close()


def make_mock_popen(pid: int = 12345, poll_returns: list | None = None) -> MagicMock:
    """Create a mock subprocess.Popen with configurable poll() behaviour."""
    proc = MagicMock()
    proc.pid = pid
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = MagicMock()

    if poll_returns is not None:
        seq = list(poll_returns)

        def _poll():
            if seq:
                return seq.pop(0)
            return 0

        proc.poll = MagicMock(side_effect=_poll)
    else:
        proc.poll = MagicMock(return_value=None)

    return proc


@contextmanager
def mock_service_deps(tmp_path, ready=True, wss=True):
    """Patch the heavy dependencies so CloudXRService construction runs without I/O.

    Yields a dict of the mock objects for assertion.  Pass ``wss=False`` to
    leave ``_start_wss_proxy_thread`` real, for tests about the proxy's own
    start-up; ``mocks["wss"]`` is then ``None``.
    """
    from isaacteleop.cloudxr.service import CloudXRService  # noqa: PLC0415

    run_dir = str(tmp_path / "run")
    logs_dir = tmp_path / "logs"
    fake_cfg = FakeEnvConfig(run_dir, logs_dir)

    mock_proc = make_mock_popen()
    wss_patch = (
        patch.object(CloudXRService, "_start_wss_proxy_thread")
        if wss
        else contextlib.nullcontext()
    )

    mocks = {}
    with (
        patch(
            "isaacteleop.cloudxr.service._service.EnvConfig.from_args",
            return_value=fake_cfg,
        ) as m_from_args,
        patch(
            "isaacteleop.cloudxr.service._service.check_eula",
        ) as m_eula,
        patch(
            "isaacteleop.cloudxr.service._service.wait_for_runtime_ready_sync",
            return_value=ready,
        ) as m_wait,
        patch(
            "isaacteleop.cloudxr.service._service.subprocess.Popen",
            return_value=mock_proc,
        ) as m_popen,
        wss_patch as m_wss,
        patch.object(
            CloudXRService,
            "_cleanup_stale_runtime",
        ) as m_cleanup,
        patch(
            "isaacteleop.cloudxr.service._service.atexit",
        ) as m_atexit,
    ):
        mocks["from_args"] = m_from_args
        mocks["check_eula"] = m_eula
        mocks["wait"] = m_wait
        mocks["popen"] = m_popen
        mocks["proc"] = mock_proc
        mocks["wss"] = m_wss
        mocks["cleanup"] = m_cleanup
        mocks["atexit"] = m_atexit
        mocks["env_cfg"] = fake_cfg
        yield mocks
