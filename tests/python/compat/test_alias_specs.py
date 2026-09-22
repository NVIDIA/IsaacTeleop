# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The alias spec is *derived*, and this is the test that keeps it that way.

`copy.copy(real_spec)` is what makes an alias spec indistinguishable from the real
one. A hand-built ModuleSpec is one line shorter and leaves
`submodule_search_locations` empty, which nothing else notices: `python -m` still
works, and `cloudxr.runtime._package_search_roots` just returns [] and reports the
vendored CloudXR runtime as absent. Delete the derivation and these go red; delete
these and the derivation is deletable.

Driven through the finder rather than `importlib.util.find_spec`: once the alias
has been imported once, `sys.modules` short-circuits `find_spec` to the real
module's own spec and the comparison becomes a spec against itself.
"""

import importlib.util
import sys

import pytest

import isaacteleop  # noqa: F401  -- installs the finder

PROBES = [
    "cloudxr",  # package
    "cloudxr.env_config",  # plain module
    "schema._schema",  # extension module
    "viz.robot.assets",  # nested module
]


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
    assert alias.submodule_search_locations == real.submodule_search_locations
    differing = {
        key
        for key in vars(alias) | vars(real)
        if vars(alias).get(key) != vars(real).get(key)
    }
    assert differing == {"name", "loader"}


def test_the_vendored_cloudxr_runtime_is_still_locatable_through_the_alias():
    from isaaccapture.cloudxr import runtime

    roots = runtime._package_search_roots("isaacteleop.cloudxr")
    assert roots == runtime._package_search_roots("isaaccapture.cloudxr")
    assert runtime._find_native_runtime_dir(
        "isaacteleop.cloudxr"
    ) == runtime._find_native_runtime_dir("isaaccapture.cloudxr")


def test_a_sibling_top_level_package_is_not_captured():
    """isaacteleop_examples is a separate distribution that was not renamed."""
    finder = _alias_finder()
    assert finder.find_spec("isaacteleop_examples") is None
    assert finder.find_spec("isaacteleop_examples.robot_viz") is None
    assert finder.find_spec("isaacteleop") is not None
    assert finder.find_spec("isaacteleop.cloudxr") is not None


def test_get_code_serves_a_package_rather_than_declining_it():
    """The freezer/bundler shape, and part of the InspectLoader contract.

    It cannot mean a broken derivation: `copy.copy` cannot drop
    `submodule_search_locations`, so a guard keyed on that only ever refused a
    legitimate caller -- while reporting the alias spec as missing a field it has.
    """
    alias = _alias_finder().find_spec("isaacteleop.cloudxr")
    assert alias.submodule_search_locations is not None

    code = alias.loader.get_code("isaacteleop.cloudxr")
    assert code.co_filename.endswith("isaaccapture/cloudxr/__init__.py")
