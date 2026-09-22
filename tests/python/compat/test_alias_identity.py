# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Both names are one module object, and the new name's namespace stays clean."""

import importlib.machinery
import importlib.util
import os
import sys

import pytest

import isaaccapture
import isaacteleop

COMPAT_ROOT = os.environ.get("ISAAC_TELEOP_COMPAT_STAGE_DIR")


def test_the_two_top_level_names_are_one_object():
    assert isaacteleop is isaaccapture


def test_a_submodule_imported_by_the_old_name_is_the_real_one():
    import isaacteleop.cloudxr  # noqa: F401

    assert sys.modules["isaacteleop.cloudxr"] is isaaccapture.cloudxr
    # Not just equal by path: pybind11 registers its types against the module
    # object, so a second copy aborts the interpreter on the duplicate.
    assert isaaccapture.cloudxr.__spec__.name == "isaaccapture.cloudxr"


def test_multi_name_from_import():
    """Served by module-level __getattr__, which is why it also passes with the
    final rebind removed -- `test_the_two_top_level_names_are_one_object` pins that."""
    from isaacteleop import deviceio, oxr

    assert deviceio is isaaccapture.deviceio
    assert oxr is isaaccapture.oxr


def test_a_dunder_main_imported_by_the_old_name_is_not_a_duplicate():
    from isaacteleop.cloudxr.service.__main__ import main

    import isaaccapture.cloudxr.service.__main__ as real

    assert main is real.main
    # The parent module is shared, so a duplicate here would be setattr'd onto
    # the *new* name's namespace and leak an isaacteleop.* __name__ into it.
    assert real.__name__.startswith("isaaccapture")


def test_the_finder_sits_immediately_before_pathfinder():
    import importlib.machinery

    names = [type(f).__name__ for f in sys.meta_path]
    alias = names.index("_AliasFinder")
    assert sys.meta_path[alias + 1] is importlib.machinery.PathFinder
    assert names.count("_AliasFinder") == 1


def test_a_reimport_serves_from_the_finder_and_installs_nothing():
    """After the first import, sys.modules['isaacteleop'] *is* isaaccapture, so a
    re-import goes through the finder rather than re-running the shim's module body."""
    before = len(sys.meta_path)
    assert sys.modules["isaacteleop"] is isaaccapture
    sys.modules.pop("isaacteleop")
    import isaacteleop as again

    assert again is isaaccapture
    assert len(sys.meta_path) == before


@pytest.mark.skipif(
    not COMPAT_ROOT, reason="ISAAC_TELEOP_COMPAT_STAGE_DIR is unset; run through ctest"
)
def test_re_executing_the_body_hands_back_a_shim_that_still_forwards():
    """Whoever holds the shim module object itself must still reach isaaccapture.

    The rebind at the end of the shim's body gives identity to ``_bootstrap._load``,
    which re-reads ``sys.modules``. It gives identity to nobody else: a
    ``module_from_spec`` + ``exec_module`` pair, and on 3.11/3.12 a second thread
    already inside ``import isaacteleop``, both hold the inert shim instead.
    Module-level ``__getattr__`` is what closes that, so this test gets the shim on
    purpose and uses it.

    Deliberately not threaded: CPython 3.13 re-reads ``sys.modules`` after the
    import lock, so the concurrent importer is handed the rebound module and the
    window cannot be observed there at all. This shape reproduces the same object
    on every interpreter, and still fails if ``__getattr__`` is removed.
    """
    # PathFinder directly: by now _AliasFinder serves "isaacteleop" and would
    # hand back the alias spec rather than the shim file's.
    spec = importlib.machinery.PathFinder.find_spec("isaacteleop", [COMPAT_ROOT])
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)

    assert shim is not isaaccapture
    assert shim.deviceio is isaaccapture.deviceio
