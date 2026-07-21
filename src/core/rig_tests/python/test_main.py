# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the python -m isaacteleop.rig CLI surface."""

from __future__ import annotations

import pytest
from rig_py_test_ns.__main__ import main


def test_bare_invocation_prints_usage_not_a_stack_trace(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "rigs/se3_tracker.yaml" in out  # one example command + pointer to rigs/


def test_missing_rig_file_is_a_friendly_error(tmp_path, capsys):
    assert main([str(tmp_path / "nope.yaml")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "rig file not found" in err


def test_invalid_rig_is_a_friendly_error(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("name: x\nunknown_key: 1\n")
    assert main([str(path)]) == 1
    assert "unknown top-level key" in capsys.readouterr().err


def test_kill_rejects_no_runtime(tmp_path, capsys):
    path = tmp_path / "rig.yaml"
    path.write_text("name: x\nconsumers:\n  - name: y\n    command: echo hi\n")
    with pytest.raises(SystemExit) as exc:
        main([str(path), "--kill", "--no-runtime"])
    assert exc.value.code == 2
    assert "--kill cannot be combined" in capsys.readouterr().err
