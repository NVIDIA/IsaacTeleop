# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Static wiring checks for `isaacteleop.viz.robot`, which no import can make for us.

Most of that package is resolved lazily, because `frames` and `scene` need the compiled
`_robot_twin` that a Windows Televiz build has no copy of. Importing a lazy module is
therefore not something a GPU-less test can do -- and a name that does not exist behind one
of those `__getattr__` entries stays invisible until a headset run reaches it.

These read the source instead. They need no backend, no GPU and no `isaacteleop` import, so
they run everywhere and catch the whole class: a relative import naming something its
target does not define, and a lazy-table entry pointing at nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from repo_paths import repo_root

ROBOT = repo_root() / "src" / "python" / "isaacteleop" / "viz" / "robot"


def _top_level_names(path: Path) -> set[str]:
    """Every name a module binds at module scope, imports included."""
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {a.asname or a.name.split(".")[0] for a in node.names}
    return names


@pytest.mark.parametrize("source", sorted(ROBOT.glob("*.py")), ids=lambda p: p.name)
def test_relative_imports_resolve(source: Path) -> None:
    """Every `from .module import name` names something that module actually defines."""
    for node in ast.walk(ast.parse(source.read_text())):
        if (
            not isinstance(node, ast.ImportFrom)
            or node.level != 1
            or node.module is None
        ):
            continue
        target = ROBOT / f"{node.module}.py"
        if not target.exists():
            # The compiled backend, which is a build artifact rather than a source file.
            assert node.module.startswith("_"), (
                f"{source.name}: no module .{node.module}"
            )
            continue
        defined = _top_level_names(target)
        for alias in node.names:
            assert alias.name == "*" or alias.name in defined, (
                f"{source.name}: `from .{node.module} import {alias.name}` but "
                f"{node.module}.py defines no {alias.name}"
            )


def test_lazy_table_resolves() -> None:
    """Every `_LAZY` entry names a real module, or a real name inside one, and every
    exported name is reachable.

    The lazy table is the one place a typo cannot fail at import time -- `__getattr__` only
    runs when somebody asks for the name, which on this package may be the first headset
    run.
    """
    tree = ast.parse((ROBOT / "__init__.py").read_text())
    lazy: dict[str, str] = {}
    modules: set[str] = set()
    exported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "_LAZY":
            lazy = {
                k.value: v.value.lstrip(".")
                for k, v in zip(node.value.keys, node.value.values)
            }
        elif target.id == "_LAZY_MODULES":
            modules = set(ast.literal_eval(node.value.args[0]))
        elif target.id == "__all__":
            exported = set(ast.literal_eval(node.value))

    assert lazy, "no _LAZY table found"
    assert modules <= set(lazy), (
        f"_LAZY_MODULES names entries not in _LAZY: {modules - set(lazy)}"
    )

    # __all__ is the supported surface and is deliberately narrower than what the package
    # defines, so lazy names need not be exported -- but an exported name that is neither
    # eagerly imported nor lazy would be an AttributeError on first use.
    eager = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    unreachable = exported - eager - set(lazy)
    assert not unreachable, f"__all__ names nothing can resolve: {sorted(unreachable)}"

    for name, module in sorted(lazy.items()):
        assert (ROBOT / f"{module}.py").exists(), (
            f"_LAZY[{name!r}] -> missing {module}.py"
        )
        if name not in modules:
            defined = _top_level_names(ROBOT / f"{module}.py")
            assert name in defined, f"_LAZY[{name!r}] -> {module}.py defines no {name}"
