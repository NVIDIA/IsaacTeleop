# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Compatibility alias: ``isaacteleop`` is ``isaaccapture``.

Every ``isaacteleop.X`` resolves to the ``isaaccapture.X`` module object itself, so
state, singletons and pybind11 type registrations are shared rather than duplicated.
See docs/source/references/migration.rst.

TODO(1.9): delete this distribution; not publishing it is what removes the alias.
"""

from __future__ import annotations

import copy
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import shlex
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

#: Isaac Sim's operator runs a bundled interpreter, where bare `pip` plausibly
#: installs into a different Python and this error then repeats verbatim. Empty on
#: some embedded interpreters, where bare `pip` is all we can honestly suggest.
#: Shell-quoted because a bundled interpreter's path can contain a space.
_PIP = f"{shlex.quote(sys.executable)} -m pip" if sys.executable else "pip"

#: Interpolated verbatim into downstream `except ImportError as e` handlers, so it
#: stays one line and carries no URL.
_MISSING_DEPENDENCY = (
    "isaacteleop is a compatibility alias for isaaccapture, which is not installed; "
    "this happens when isaacteleop was installed with --no-deps. "
    f"Run `{_PIP} install isaaccapture`"
)


def _renamed(fullname: str) -> str:
    return _NEW_PACKAGE + fullname[len(_OLD_PACKAGE) :]


def __getattr__(name: str) -> Any:
    # Defined before anything else runs, because a thread that enters
    # `import isaacteleop` while the body below is still executing is handed *this*
    # module: _find_and_load captures sys.modules[name] before it waits on the
    # import lock and never re-reads it, so the rebind at the end cannot reach it.
    # The window is the whole of import_module(_NEW_PACKAGE) -- every pybind11
    # extension. Same object, same fix, for module_from_spec + exec_module.
    return getattr(importlib.import_module(_NEW_PACKAGE), name)


class _AliasLoader(importlib.abc.Loader):
    """Binds the old name to the module object the new name already resolves to."""

    def __init__(self, real: importlib.machinery.ModuleSpec) -> None:
        self._real = real

    def exec_module(self, module: ModuleType) -> None:
        # _bootstrap._load re-reads sys.modules[spec.name] after exec_module, so
        # replacing the entry here is what makes isaacteleop.X *be* isaaccapture.X.
        sys.modules[module.__name__] = importlib.import_module(
            _renamed(module.__name__)
        )

    def get_code(self, fullname: str) -> CodeType | None:
        # runpy asks the loader, not the module, so `python -m isaacteleop.X` needs
        # this. Delegate for packages too: runpy recurses into X.__main__ through
        # submodule_search_locations, which copy.copy carries over, and a freezer
        # asking a package directly wants __init__'s code, as InspectLoader says.
        return self._real.loader.get_code(_renamed(fullname))


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Serves every isaacteleop.* name from the isaaccapture spec."""

    #: Recognised by _install() across a re-execution of this module, where a
    #: fresh class object makes isinstance useless.
    _is_alias_finder = True

    def find_spec(self, fullname, path=None, target=None):
        # Exact-or-dotted: isaacteleop_examples is a different, unrenamed package.
        if fullname != _OLD_PACKAGE and not fullname.startswith(_OLD_PACKAGE + "."):
            return None
        real = importlib.util.find_spec(_renamed(fullname))
        if real is None:
            return None
        # copy.copy, not a hand-built ModuleSpec: there is then no field to forget.
        # submodule_search_locations in particular is what runpy reads to find
        # X.__main__ and what cloudxr.runtime reads to find the vendored
        # libcloudxr.so, and a hand-built spec leaves it empty with no symptom.
        spec = copy.copy(real)
        spec.name = fullname
        spec.loader = _AliasLoader(real)
        return spec


def _install() -> None:
    # Immediately before PathFinder. Appending is not a style choice: PathFinder
    # then reaches the aliased parent's real __path__ first and loads the pybind11
    # extensions a second time, which aborts the interpreter on a duplicate type
    # registration. The fallback is 0, never the end: an embedded or instrumented
    # interpreter that wraps PathFinder leaves the identity search with no match,
    # and the end is that same append.
    if any(getattr(finder, "_is_alias_finder", False) for finder in sys.meta_path):
        return
    at = next(
        (
            index
            for index, finder in enumerate(sys.meta_path)
            if finder is importlib.machinery.PathFinder
        ),
        0,
    )
    sys.meta_path.insert(at, _AliasFinder())


def _default_deprecation_policy_intact() -> bool:
    """True if nothing in this process has an opinion about DeprecationWarning.

    PEP 565: Python shows one raised from ``__main__`` and hides it elsewhere, so a
    ``__main__`` probe reaching a recorder means that default is still in force.
    Do not replace this with a scan of ``warnings.filters``: ``simplefilter("ignore",
    DeprecationWarning)`` installs a tuple identical to CPython's own default entry,
    so only ordering separates them and the machinery already applies it.
    ``sys.warnoptions`` sees neither that call nor pytest's ``filterwarnings`` ini,
    which routes through the same API.
    """
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

    Default filters hide a DeprecationWarning raised from importlib, which is every
    ``python -m isaacteleop.X``, so the stderr line is not redundant -- it is the
    branch most imports take, and it carries the same ``file:line``.

    ``stacklevel=3`` is warn -> this function -> the module body -> the importing line.
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
        # Re-emitted under `always` into a recorder purely to resolve the location,
        # so this branch names the importing line without a second implementation of
        # importlib-frame skipping. Same stacklevel, so the two cannot drift, and
        # `always` cannot be filtered out, so `located` always holds one entry.
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

# _announce() is before _install() for the same reason: under
# -W error::DeprecationWarning it raises, and a finder left behind would serve
# every later import in that process silently -- which is what makes `-W error`
# unenforceable and turns `try: import isaacteleop` into a pass.
_announce()
_install()
# What makes `isaacteleop is isaaccapture` hold: without it sys.modules keeps this
# shim under the old name. Do not check it by `from isaacteleop import deviceio` --
# module-level __getattr__ serves that either way.
sys.modules[__name__] = importlib.import_module(_NEW_PACKAGE)
