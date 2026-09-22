# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Driven through the finder: once the alias has been imported, `sys.modules`
short-circuits `importlib.util.find_spec` to the real module's own spec.
"""

import importlib.util
import sys

import pytest

import isaacteleop  # noqa: F401  -- installs the finder

#: A package, so submodule_search_locations is populated -- the field a hand-built
#: spec silently leaves empty.
PROBES = ["cloudxr"]


def _alias_finder():
    finders = [f for f in sys.meta_path if type(f).__name__ == "_AliasFinder"]
    assert len(finders) == 1, finders
    return finders[0]


@pytest.mark.parametrize("suffix", PROBES)
def test_the_alias_spec_differs_only_in_name_and_loader(suffix):
    real = importlib.util.find_spec(f"isaaccapture.{suffix}")
    alias = _alias_finder().find_spec(f"isaacteleop.{suffix}")

    assert alias is not None
    assert alias.name == f"isaacteleop.{suffix}"
    assert alias.loader is not real.loader
    # runpy reads submodule_search_locations to find X.__main__, and
    # cloudxr.runtime reads it to find the vendored libcloudxr.so.
    assert alias.submodule_search_locations == real.submodule_search_locations


def test_the_vendored_cloudxr_runtime_is_still_locatable_through_the_alias():
    from isaaccapture.cloudxr import runtime

    roots = runtime._package_search_roots("isaacteleop.cloudxr")
    assert roots == runtime._package_search_roots("isaaccapture.cloudxr")
    assert runtime._find_native_runtime_dir(
        "isaacteleop.cloudxr"
    ) == runtime._find_native_runtime_dir("isaaccapture.cloudxr")


def test_a_sibling_top_level_package_is_not_captured():
    """The alias owns `isaacteleop` alone.

    Without the exact-or-dotted guard `isaacteleop_examples` prefix-matches, and
    `_renamed` turns it into `isaaccapture_examples`, which does exist.
    """
    finder = _alias_finder()
    assert finder.find_spec("isaacteleop_examples") is None
    assert finder.find_spec("isaacteleop_examples.robot_viz") is None
    assert finder.find_spec("isaacteleop") is not None
    assert finder.find_spec("isaacteleop.cloudxr") is not None
