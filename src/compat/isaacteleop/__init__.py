# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compatibility alias: ``isaacteleop`` is ``isaaccapture``.

Every ``isaacteleop.X`` is the ``isaaccapture.X`` module object itself, so pybind11
type registrations are not duplicated. See docs/source/references/migration.rst.
TODO(1.9): delete this distribution.
"""

from __future__ import annotations

import copy
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import warnings
from types import CodeType, ModuleType
from typing import Any

_OLD_PACKAGE = "isaacteleop"
_NEW_PACKAGE = "isaaccapture"

_DEPRECATION = (
    "The 'isaacteleop' import package was renamed to 'isaaccapture' in Isaac Teleop "
    "1.6; import 'isaaccapture' instead. The alias will be removed in 1.9 -- inside "
    "the 1.x series, so pin 'isaacteleop<1.9', not 'isaacteleop<2', if you need time. "
    "See https://nvidia.github.io/IsaacTeleop/main/references/migration.html"
)

#: Interpolated verbatim into downstream `except ImportError as e` handlers, so it
#: stays one line and carries no URL.
_MISSING_DEPENDENCY = (
    "isaacteleop is a compatibility alias for isaaccapture, which is not installed; "
    "usually a --no-deps install, or isaaccapture removed on its own. "
    "Run `pip install isaaccapture`"
)


def _renamed(fullname: str) -> str:
    return _NEW_PACKAGE + fullname[len(_OLD_PACKAGE) :]


def __getattr__(name: str) -> Any:
    # Defined before the body runs: a holder of this module pre-rebind lands here.
    return getattr(importlib.import_module(_NEW_PACKAGE), name)


class _AliasLoader(importlib.abc.Loader):
    """Binds the old name to the module object the new name already resolves to."""

    def __init__(self, real: importlib.machinery.ModuleSpec) -> None:
        self._real = real

    def exec_module(self, module: ModuleType) -> None:
        # _bootstrap._load re-reads sys.modules[spec.name] after exec_module.
        sys.modules[module.__name__] = importlib.import_module(
            _renamed(module.__name__)
        )

    def get_code(self, fullname: str) -> CodeType | None:
        # runpy asks the loader, not the module, for `python -m isaacteleop.X`.
        return self._real.loader.get_code(_renamed(fullname))


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Serves every isaacteleop.* name from the isaaccapture spec."""

    def find_spec(self, fullname, path=None, target=None):
        # Exact-or-dotted: `isaacteleop_examples` would otherwise prefix-match.
        if fullname != _OLD_PACKAGE and not fullname.startswith(_OLD_PACKAGE + "."):
            return None
        real = importlib.util.find_spec(_renamed(fullname))
        if real is None:
            return None
        # copy.copy carries submodule_search_locations, which runpy reads to find
        # X.__main__ and cloudxr.runtime reads to find the vendored libcloudxr.so.
        spec = copy.copy(real)
        spec.name = fullname
        spec.loader = _AliasLoader(real)
        return spec


def _install() -> None:
    # Before PathFinder: it would otherwise reach the aliased parent's real __path__
    # and load the pybind11 extensions twice, aborting on a duplicate registration.
    sys.meta_path.insert(0, _AliasFinder())


def _default_deprecation_policy_intact() -> bool:
    """True if nothing in this process has an opinion about DeprecationWarning.

    PEP 565: Python shows one raised from ``__main__`` and hides it elsewhere.
    """
    # Not a warnings.filters scan: simplefilter("ignore") installs CPython's own tuple.
    try:
        # _DEPRECATION verbatim, so a message-regex filter matches the probe too.
        with warnings.catch_warnings(record=True) as probe:
            warnings.warn_explicit(
                _DEPRECATION,
                DeprecationWarning,
                __file__,
                0,
                module="__main__",
                registry={},
            )
    except DeprecationWarning:
        return False  # An `error` filter is an opinion too.
    return bool(probe)


def _announce() -> None:
    """Emit the notice once, on whichever channel is not filtered out.

    Default filters hide it raised from importlib -- every ``python -m isaacteleop.X``.
    """
    shown = False
    previous = warnings.showwarning

    def _probe(*args, **kwargs):
        nonlocal shown
        shown = True
        previous(*args, **kwargs)

    warnings.showwarning = _probe
    try:
        warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=3)
    finally:
        warnings.showwarning = previous
    if not shown and _default_deprecation_policy_intact():
        # Re-emitted under `always` only to resolve the importing file:line.
        with warnings.catch_warnings(record=True) as located:
            warnings.simplefilter("always")
            warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=3)
        print(
            f"{located[0].filename}:{located[0].lineno}: {_DEPRECATION}",
            file=sys.stderr,
        )


# Before _install(), so a --no-deps install never leaves a finder behind.
if importlib.util.find_spec(_NEW_PACKAGE) is None:
    raise ImportError(_MISSING_DEPENDENCY)

# _announce() before _install() for the same reason: under -W error::DeprecationWarning
# it raises, and a finder left behind would serve every later import silently.
_announce()
_install()
# Without this rebind, sys.modules keeps the shim under the old name.
sys.modules[__name__] = importlib.import_module(_NEW_PACKAGE)
