# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Schema and loader for teleop-rig YAML files.

A *rig* file describes one tmux teleop rig: the CloudXR runtime pane plus
producer plugins and consumer apps. See ``rigs/se3_tracker.yaml`` in the
Teleop repository for an annotated exemplar. Top-level keys::

    name:         rig id AND tmux session name (required)
    description:  free text (optional)
    cwd:          working dir for every pane, relative to the YAML file's
                  directory (optional; default: the YAML's directory)
    params:       flat str->scalar dict of {placeholder} values shared by
                  the commands below; edit the file to change them (optional)
    runtime:      full-command override for the runtime pane (optional;
                  default: "{python} -m isaacteleop.cloudxr --accept-eula")
    producers:    list of {name, command} — publish device data (optional)
    consumers:    list of {name, command} — read the streams (optional)

At least one producer or consumer is required. Unknown keys are a hard
error. Commands are shell strings typed verbatim into panes; ``{key}``
placeholders are substituted from ``params`` (literal braces must be
escaped as ``{{`` / ``}}``). The reserved ``{python}`` placeholder expands
to the launching interpreter (:data:`sys.executable`).
"""

from __future__ import annotations

import dataclasses
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

#: Reserved placeholder expanding to the launching interpreter.
PYTHON_PLACEHOLDER = "python"

#: Default runtime pane command (used when the rig has no ``runtime:`` key).
DEFAULT_RUNTIME_COMMAND = "{python} -m isaacteleop.cloudxr --accept-eula"

#: Flag a Python TeleopSession script needs so it does not start a second
#: (host-singleton) CloudXR runtime next to the managed runtime pane.
NO_LAUNCH_RUNTIME_FLAG = "--no-launch-cloudxr-runtime"

_TOP_LEVEL_KEYS = frozenset(
    {"name", "description", "cwd", "params", "runtime", "producers", "consumers"}
)
_ENTRY_KEYS = frozenset({"name", "command"})

#: ``name:`` doubles as the tmux session name, so keep it shell/tmux-safe
#: (tmux targets treat ``.`` and ``:`` specially; spaces need quoting).
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RigError(Exception):
    """Base class for user-facing rig-launcher errors (no stack trace)."""


class RigConfigError(RigError):
    """A rig YAML file is invalid."""


@dataclasses.dataclass(frozen=True)
class ProcessConfig:
    """One producer or consumer pane: display name + raw command string."""

    name: str
    command: str


@dataclasses.dataclass(frozen=True)
class RigConfig:
    """A parsed teleop rig (see the module docstring for the YAML schema)."""

    name: str
    description: str
    cwd: Path
    params: dict[str, str]
    runtime: str | None
    producers: tuple[ProcessConfig, ...]
    consumers: tuple[ProcessConfig, ...]
    source: Path

    @property
    def runtime_command(self) -> str:
        """The raw (unsubstituted) runtime pane command."""
        return self.runtime if self.runtime is not None else DEFAULT_RUNTIME_COMMAND


def _require_str(value: Any, what: str, source: Path) -> str:
    """Return *value* if it is a non-empty string; hard error otherwise."""
    if not isinstance(value, str) or not value.strip():
        raise RigConfigError(f"{source}: {what} must be a non-empty string")
    return value


def _parse_entries(value: Any, role: str, source: Path) -> tuple[ProcessConfig, ...]:
    """Parse a ``producers:`` / ``consumers:`` list of {name, command} dicts."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RigConfigError(
            f"{source}: '{role}' must be a list of {{name, command}} entries"
        )
    entries = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RigConfigError(
                f"{source}: {role}[{i}] must be a mapping with 'name' and 'command' keys"
            )
        unknown = sorted(set(entry) - _ENTRY_KEYS)
        if unknown:
            raise RigConfigError(
                f"{source}: unknown key(s) {unknown} in {role}[{i}] "
                f"(each entry takes exactly: name, command)"
            )
        missing = sorted(_ENTRY_KEYS - set(entry))
        if missing:
            raise RigConfigError(
                f"{source}: {role}[{i}] is missing required key(s) {missing}"
            )
        entries.append(
            ProcessConfig(
                name=_require_str(entry["name"], f"{role}[{i}].name", source),
                command=_require_str(entry["command"], f"{role}[{i}].command", source),
            )
        )
    return tuple(entries)


def _parse_params(value: Any, source: Path) -> dict[str, str]:
    """Parse the ``params:`` mapping; scalars are coerced to strings."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RigConfigError(f"{source}: 'params' must be a mapping of KEY: value")
    params: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str):
            raise RigConfigError(
                f"{source}: 'params' keys must be strings (got {key!r})"
            )
        if key == PYTHON_PLACEHOLDER:
            raise RigConfigError(
                f"{source}: param '{PYTHON_PLACEHOLDER}' is reserved "
                "(it always expands to the launching interpreter)"
            )
        if isinstance(val, (dict, list)):
            raise RigConfigError(f"{source}: param '{key}' must be a scalar")
        params[key] = str(val)
    return params


def load_rig_config(path: str | Path) -> RigConfig:
    """Load and validate a rig YAML file.

    Args:
        path: Path to the rig file (e.g. ``rigs/se3_tracker.yaml``).

    Returns:
        The validated :class:`RigConfig`. ``cwd`` is resolved to an
        absolute path against the YAML file's directory.

    Raises:
        RigConfigError: On a missing file, YAML parse error, unknown or
            missing keys, or invalid values.
    """
    source = Path(path)
    if not source.is_file():
        raise RigConfigError(
            f"rig file not found: {source} — see rigs/se3_tracker.yaml in the "
            "Teleop repository for an example"
        )
    try:
        data = yaml.safe_load(source.read_text())
    except yaml.YAMLError as exc:
        raise RigConfigError(
            f"{source}: invalid YAML: {exc} — see rigs/se3_tracker.yaml for a valid example"
        ) from exc
    if not isinstance(data, dict):
        raise RigConfigError(f"{source}: top level must be a mapping of rig keys")

    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise RigConfigError(
            f"{source}: unknown top-level key(s) {unknown} "
            f"(known keys: {', '.join(sorted(_TOP_LEVEL_KEYS))})"
        )
    if "name" not in data:
        raise RigConfigError(f"{source}: missing required key 'name'")

    name = _require_str(data["name"], "'name'", source)
    if not _NAME_PATTERN.match(name):
        raise RigConfigError(
            f"{source}: name '{name}' is used as the tmux session name — "
            "use letters/digits/-/_ only"
        )
    description = ""
    if data.get("description") is not None:
        description = _require_str(data["description"], "'description'", source)
    runtime = None
    if data.get("runtime") is not None:
        runtime = _require_str(data["runtime"], "'runtime'", source)

    yaml_dir = source.resolve().parent
    cwd = yaml_dir
    if data.get("cwd") is not None:
        cwd = (yaml_dir / _require_str(data["cwd"], "'cwd'", source)).resolve()

    producers = _parse_entries(data.get("producers"), "producers", source)
    consumers = _parse_entries(data.get("consumers"), "consumers", source)
    if not producers and not consumers:
        raise RigConfigError(
            f"{source}: rig must define at least one producer or consumer"
        )

    return RigConfig(
        name=name,
        description=description,
        cwd=cwd,
        params=_parse_params(data.get("params"), source),
        runtime=runtime,
        producers=producers,
        consumers=consumers,
        source=source,
    )


def substitute_command(command: str, params: Mapping[str, str], source: Path) -> str:
    """Expand ``{key}`` placeholders in a command string.

    ``{python}`` expands to the quoted launching interpreter; every other
    placeholder must be declared in *params*.

    Raises:
        RigConfigError: On an unknown placeholder or malformed braces
            (literal braces must be escaped as ``{{`` / ``}}``).
    """
    # A plain dict raises KeyError from format_map on unknown placeholders.
    table = dict(params)
    table[PYTHON_PLACEHOLDER] = shlex.quote(sys.executable)
    try:
        return command.format_map(table)
    except KeyError as exc:
        raise RigConfigError(
            f"{source}: unknown placeholder {{{exc.args[0]}}} in command {command!r} "
            f"— declare it under 'params:' (literal braces must be escaped as {{{{ / }}}})"
        ) from exc
    except (ValueError, IndexError) as exc:
        raise RigConfigError(
            f"{source}: malformed placeholder in command {command!r}: {exc} "
            f"(literal braces must be escaped as {{{{ / }}}})"
        ) from exc


def find_runtime_footguns(
    processes: Sequence[ProcessConfig], runtime_managed: bool
) -> list[str]:
    """Warn-only lint: pre-typed Python commands that would self-launch a runtime.

    Python TeleopSession scripts launch their own CloudXR runtime by
    default. The runtime is a host singleton (fixed WSS port), so a second
    runtime KILLS the managed runtime pane — the headset drops and every
    producer stalls. Heuristic (narrow, never a gate): the managed runtime
    pane is enabled AND a pre-typed command contains ``{python}`` and a
    ``.py`` token or ``-m isaacteleop`` AND lacks ``--no-launch-cloudxr-runtime``.

    Returns:
        Warning strings to print; empty when nothing looks risky.
    """
    if not runtime_managed:
        return []
    warnings = []
    for proc in processes:
        cmd = proc.command
        if "{python}" not in cmd or NO_LAUNCH_RUNTIME_FLAG in cmd:
            continue
        looks_python_app = "-m isaacteleop" in cmd or any(
            token.endswith(".py") for token in cmd.split()
        )
        if looks_python_app:
            warnings.append(
                f"warning: '{proc.name}' looks like a Python TeleopSession script "
                f"without {NO_LAUNCH_RUNTIME_FLAG}. Such scripts start their own "
                "CloudXR runtime by default; the runtime is a host singleton, so a "
                "second runtime kills the runtime pane — the headset drops and "
                f"producers stall. Add {NO_LAUNCH_RUNTIME_FLAG} to its command."
            )
    return warnings
