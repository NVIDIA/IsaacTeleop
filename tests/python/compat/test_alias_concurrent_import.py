# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Whoever is handed the shim module object itself must still reach isaaccapture.

The rebind at the end of the shim's body gives identity to ``_bootstrap._load``,
which re-reads ``sys.modules``. It gives identity to nobody else: a second thread
already inside ``import isaacteleop``, and a ``module_from_spec`` + ``exec_module``
pair, both hold the inert shim instead. Module-level ``__getattr__`` is what closes
that, so these tests get the shim on purpose and use it.

Own file because the first test needs an interpreter in which nothing has imported
isaaccapture yet -- ctest gives each file its own process.
"""

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
import threading
import time

import pytest

COMPAT_ROOT = os.environ.get("ISAAC_TELEOP_COMPAT_STAGE_DIR")

pytestmark = pytest.mark.skipif(
    not COMPAT_ROOT, reason="ISAAC_TELEOP_COMPAT_STAGE_DIR is unset; run through ctest"
)


class _Gate(importlib.abc.MetaPathFinder):
    """Holds the first isaaccapture lookup open, then gets out of the way.

    Always returns None, so resolution carries on down ``sys.meta_path``; the only
    effect is the wait. Without it the window is real but timing-dependent -- it is
    the whole eager import of every pybind11 extension, hundreds of milliseconds on
    Orin, but a few on a warm x86 page cache.
    """

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.opened = threading.Event()

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "isaaccapture" and not self.opened.is_set():
            self.reached.set()
            self.opened.wait(30)
        return None


def test_a_thread_that_arrives_mid_body_gets_a_working_module():
    assert "isaaccapture" not in sys.modules, "must be the first test in this process"

    gate = _Gate()
    sys.meta_path.insert(0, gate)
    captured: dict[str, object] = {}
    entering = threading.Event()

    def _first():
        import isaacteleop  # noqa: F401

    def _second():
        entering.set()
        import isaacteleop

        captured["module"] = isaacteleop

    first = threading.Thread(target=_first)
    first.start()
    assert gate.reached.wait(30), "the first import never reached isaaccapture"

    second = threading.Thread(target=_second)
    second.start()
    # The second thread is one statement from sys.modules.get("isaacteleop"), and
    # blocks on the import lock for as long as the gate is shut.
    assert entering.wait(30)
    time.sleep(0.1)
    gate.opened.set()

    first.join(60)
    second.join(60)
    sys.meta_path.remove(gate)

    import isaaccapture

    # Proves the window was caught: after the rebind the second import would have
    # been handed isaaccapture itself and there would be nothing to forward.
    assert captured["module"] is not isaaccapture
    assert captured["module"].deviceio is isaaccapture.deviceio


def test_re_executing_the_body_hands_back_a_shim_that_still_forwards():
    """The documented ``module_from_spec`` + ``exec_module`` recipe, which is the
    same object a concurrent importer holds -- deterministically, no threads."""
    import isaaccapture

    # PathFinder directly: by now _AliasFinder serves "isaacteleop" and would
    # hand back the alias spec rather than the shim file's.
    spec = importlib.machinery.PathFinder.find_spec("isaacteleop", [COMPAT_ROOT])
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)

    assert shim is not isaaccapture
    assert shim.deviceio is isaaccapture.deviceio
