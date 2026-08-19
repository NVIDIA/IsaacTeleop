# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for ``python -m isaacteleop.rig``.

Launches a teleop rig (CloudXR runtime + producer plugins + consumer apps)
in a tmux window from a YAML rig file.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from .config import RigError, load_rig_config
from .launcher import kill_rig, launch_rig

_EXAMPLE = (
    "example (from the Teleop repository root):\n"
    "  python -m isaacteleop.rig rigs/se3_tracker.yaml\n"
    "rig files live in the Teleop repository under rigs/"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m isaacteleop.rig",
        description="Launch a teleop rig (CloudXR runtime + producers + consumers) in tmux",
        epilog=_EXAMPLE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "rig",
        nargs="?",
        metavar="RIG_YAML",
        help="Path to a rig file (e.g. rigs/se3_tracker.yaml).",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help=(
            "Kill the rig's tmux window (and every process in it) instead "
            "of launching, e.g. to relaunch after editing the rig file."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code (never a stack trace)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.rig is None:
        parser.print_usage()
        print(_EXAMPLE)
        return 0

    try:
        config = load_rig_config(args.rig)
        if args.kill:
            kill_rig(config)
        else:
            launch_rig(config)
    except RigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        detail = f": {stderr}" if stderr else ""
        print(f"error: tmux command failed ({exc}){detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
