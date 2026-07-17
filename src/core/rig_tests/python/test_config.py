# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the teleop-rig YAML schema and loader."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest
from rig_py_test_ns.config import (
    DEFAULT_RUNTIME_COMMAND,
    RigConfigError,
    ProcessConfig,
    find_runtime_footguns,
    load_rig_config,
    substitute_command,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SE3_RIG = REPO_ROOT / "rigs" / "se3_tracker.yaml"


def write_rig(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rig.yaml"
    path.write_text(body)
    return path


MINIMAL = """
name: mini
consumers:
  - name: printer
    command: "echo hi"
"""


# ---------------------------------------------------------------------------
# Loading the shipped exemplar
# ---------------------------------------------------------------------------


def test_load_se3_rig():
    config = load_rig_config(SE3_RIG)
    assert config.name == "se3_tracker"
    assert config.description
    assert config.cwd == REPO_ROOT  # cwd: .. resolves against rigs/
    assert config.runtime is None
    assert config.runtime_command == DEFAULT_RUNTIME_COMMAND
    assert config.params == {"hand": "right", "collection_id": "se3_tracker"}
    assert len(config.producers) == 1
    assert len(config.consumers) == 1
    # collection_id is single-sourced: both sides reference the placeholder.
    assert "{collection_id}" in config.producers[0].command
    assert "{collection_id}" in config.consumers[0].command


def test_se3_rig_has_no_footguns():
    config = load_rig_config(SE3_RIG)
    assert (
        find_runtime_footguns(
            [*config.producers, *config.consumers], runtime_managed=True
        )
        == []
    )


# ---------------------------------------------------------------------------
# Validation errors (each a hard error naming the file)
# ---------------------------------------------------------------------------


def test_missing_file_is_config_error(tmp_path):
    with pytest.raises(RigConfigError, match="rig file not found"):
        load_rig_config(tmp_path / "nope.yaml")


def test_invalid_yaml_is_config_error(tmp_path):
    path = write_rig(tmp_path, "name: [unclosed")
    with pytest.raises(RigConfigError, match="invalid YAML"):
        load_rig_config(path)


def test_unknown_top_level_key_is_hard_error(tmp_path):
    path = write_rig(tmp_path, MINIMAL + "streams: {}\n")
    with pytest.raises(RigConfigError, match=r"unknown top-level key.*streams"):
        load_rig_config(path)


def test_missing_name_is_hard_error(tmp_path):
    path = write_rig(tmp_path, "consumers:\n  - name: x\n    command: y\n")
    with pytest.raises(RigConfigError, match="missing required key 'name'"):
        load_rig_config(path)


def test_rig_without_processes_is_hard_error(tmp_path):
    path = write_rig(tmp_path, "name: empty\n")
    with pytest.raises(RigConfigError, match="at least one producer or consumer"):
        load_rig_config(path)


def test_unknown_entry_key_is_hard_error(tmp_path):
    path = write_rig(
        tmp_path,
        "name: x\nconsumers:\n  - name: y\n    command: z\n    autostart: true\n",
    )
    with pytest.raises(RigConfigError, match=r"unknown key.*autostart"):
        load_rig_config(path)


def test_entry_missing_command_is_hard_error(tmp_path):
    path = write_rig(tmp_path, "name: x\nproducers:\n  - name: y\n")
    with pytest.raises(RigConfigError, match=r"missing required key.*command"):
        load_rig_config(path)


def test_tmux_safe_name_is_accepted(tmp_path):
    path = write_rig(tmp_path, MINIMAL.replace("name: mini", "name: Se3-Rig_2"))
    assert load_rig_config(path).name == "Se3-Rig_2"


@pytest.mark.parametrize("bad_name", ["se3 rig", "se3:rig", "se3.rig", "r'ig"])
def test_tmux_unsafe_name_is_hard_error(tmp_path, bad_name):
    path = write_rig(tmp_path, MINIMAL.replace("name: mini", f'name: "{bad_name}"'))
    with pytest.raises(RigConfigError, match="used as the tmux session name"):
        load_rig_config(path)


def test_param_named_python_is_reserved(tmp_path):
    path = write_rig(tmp_path, MINIMAL + "params:\n  python: /usr/bin/python\n")
    with pytest.raises(RigConfigError, match="reserved"):
        load_rig_config(path)


# ---------------------------------------------------------------------------
# cwd resolution
# ---------------------------------------------------------------------------


def test_cwd_defaults_to_yaml_directory(tmp_path):
    path = write_rig(tmp_path, MINIMAL)
    assert load_rig_config(path).cwd == tmp_path.resolve()


def test_cwd_resolves_relative_to_yaml_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    path = tmp_path / "sub" / "rig.yaml"
    path.write_text(MINIMAL + "cwd: ..\n")
    assert load_rig_config(path).cwd == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------


def test_python_placeholder_expands_to_sys_executable(tmp_path):
    result = substitute_command(
        "{python} -m isaacteleop.cloudxr", {}, tmp_path / "c.yaml"
    )
    assert result == f"{shlex.quote(sys.executable)} -m isaacteleop.cloudxr"


def test_params_substituted(tmp_path):
    result = substitute_command(
        "./plugin {hand} {collection_id}",
        {"hand": "left", "collection_id": "abc"},
        tmp_path / "c.yaml",
    )
    assert result == "./plugin left abc"


def test_unknown_placeholder_is_hard_error(tmp_path):
    with pytest.raises(RigConfigError, match=r"unknown placeholder \{hand\}") as exc:
        substitute_command("./plugin {hand}", {}, tmp_path / "c.yaml")
    # The remedy mentions brace escaping.
    assert "{{" in str(exc.value)


def test_malformed_brace_is_hard_error_mentioning_escaping(tmp_path):
    with pytest.raises(RigConfigError, match=r"\{\{"):
        substitute_command("echo ${VAR:-x}", {}, tmp_path / "c.yaml")


def test_escaped_braces_pass_through(tmp_path):
    assert (
        substitute_command("echo {{literal}}", {}, tmp_path / "c.yaml")
        == "echo {literal}"
    )


# ---------------------------------------------------------------------------
# Foot-gun lint (warn-only, narrow)
# ---------------------------------------------------------------------------


def _proc(command: str) -> ProcessConfig:
    return ProcessConfig(name="app", command=command)


def test_footgun_fires_on_python_script_without_flag():
    warnings = find_runtime_footguns(
        [_proc("{python} examples/teleop/python/example.py {collection_id}")],
        runtime_managed=True,
    )
    assert len(warnings) == 1
    assert "--no-launch-cloudxr-runtime" in warnings[0]
    # Names the symptom, not just the flag.
    assert "kills the runtime pane" in warnings[0]


def test_footgun_fires_on_module_invocation():
    warnings = find_runtime_footguns(
        [_proc("{python} -m isaacteleop.examples.foo")], runtime_managed=True
    )
    assert len(warnings) == 1


def test_footgun_quiet_when_flag_present():
    assert (
        find_runtime_footguns(
            [_proc("{python} example.py --no-launch-cloudxr-runtime")],
            runtime_managed=True,
        )
        == []
    )


def test_footgun_quiet_on_cpp_binary():
    assert (
        find_runtime_footguns(
            [_proc("install/examples/schemaio/se3_printer {collection_id}")],
            runtime_managed=True,
        )
        == []
    )


def test_footgun_quiet_when_runtime_not_managed():
    assert (
        find_runtime_footguns([_proc("{python} example.py")], runtime_managed=False)
        == []
    )
