# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Both names are one module object, and the new name's namespace stays clean."""

import sys

import isaaccapture
import isaacteleop


def test_the_two_top_level_names_are_one_object():
    assert isaacteleop is isaaccapture


def test_a_submodule_imported_by_the_old_name_is_the_real_one():
    import isaacteleop.cloudxr  # noqa: F401

    assert sys.modules["isaacteleop.cloudxr"] is isaaccapture.cloudxr
    # Not just equal by path: pybind11 registers its types against the module
    # object, so a second copy aborts the interpreter on the duplicate.
    assert isaaccapture.cloudxr.__spec__.name == "isaaccapture.cloudxr"


def test_multi_name_from_import():
    """The shape that fails without `sys.modules[__name__] = isaaccapture`."""
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
