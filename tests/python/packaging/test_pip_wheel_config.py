# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Only `isaaccapture` may reach the pip-built wheel.

`wheel.packages` is also what feeds the editable redirect, so `isaacteleop` is
declared there to make `pip install -e .` resolve it -- and must then be excluded,
or `pip install .` ships the shim inside the isaaccapture distribution, which is
the one outcome the split exists to prevent. Nothing else checks that wheel: the
classic wheels are covered by test_wheel_contents.py, and the editable half by the
pip-editable-install CI job. This is config shape only; it cannot catch
scikit-build-core changing what `wheel.exclude` applies to.
"""

from __future__ import annotations

import tomllib

from repo_paths import repo_root

SHIPPED = "isaaccapture"


def test_every_declared_package_but_isaaccapture_is_excluded() -> None:
    text = (repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    wheel = tomllib.loads(text)["tool"]["scikit-build"]["wheel"]
    extra = set(wheel["packages"]) - {SHIPPED}
    assert {f"{name}/**" for name in extra} <= set(wheel.get("exclude", []))
