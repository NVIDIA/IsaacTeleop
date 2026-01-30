#!/usr/bin/env python3
"""
Sharpa HA4 variant of `retarget_openxr26_with_g1_upper_body.py`.

This is a thin wrapper that reuses the standalone dex-retargeting pipeline, but sets
the default dex-retargeting YAML config filenames to:
  - sharpa_ha4_left_dexpilot.yml
  - sharpa_ha4_right_dexpilot.yml

Usage is intentionally identical to the G1 script; just swap the script path and URDFs:

  python3 dyn-hamr/retarget_openxr26_with_sharpa_upper_body.py \\
    --input <openxr26 .npz or dir> \\
    --output <out_dir> \\
    --left-hand-urdf  /path/to/left_sharpa_ha4_v2_1.urdf \\
    --right-hand-urdf /path/to/right_sharpa_ha4_v2_1.urdf
"""

from __future__ import annotations

import sys


def _ensure_default(argv: list[str], flag: str, value: str) -> list[str]:
    # Only append if the user didn't explicitly set it.
    return argv if flag in argv else (argv + [flag, value])


def main() -> None:
    # Import the full implementation (kept in the G1 script for historical reasons).
    import retarget_openxr26_with_g1_upper_body as base  # noqa: WPS433

    argv = sys.argv[1:]
    argv = _ensure_default(argv, "--left-config", "sharpa_ha4_left_dexpilot.yml")
    argv = _ensure_default(argv, "--right-config", "sharpa_ha4_right_dexpilot.yml")

    # Forward to the underlying implementation.
    sys.argv = [sys.argv[0]] + argv
    base.main()


if __name__ == "__main__":
    main()


