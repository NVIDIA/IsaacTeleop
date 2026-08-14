# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deprecated alias for ``python -m isaacteleop.cloudxr.service run``."""

import sys

from isaacteleop.cloudxr.service.__main__ import main as service_main

# TODO(1.7): remove this module.
_DEPRECATION = (
    "python -m isaacteleop.cloudxr is deprecated and will be removed in "
    "Isaac Teleop 1.7; use python -m isaacteleop.cloudxr.service run"
)


def main(argv: list[str] | None = None) -> int:
    """Warn, then run the service with the arguments given here."""
    print(f"\033[33m{_DEPRECATION}\033[0m", file=sys.stderr)
    return service_main(["run", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    sys.exit(main())
