# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Record a live OpenXR hand-tracking session to an MCAP file.

``CloudXRLauncher`` starts the CloudXR runtime and WSS proxy automatically —
no separate terminal or pre-running headset daemon is needed. The pipeline in
``common.py`` wires only ``HandsSource``, so ``TeleopSession`` records exactly
the ``hands`` channel — no head, no controllers.

Usage:
    python record_hand.py [duration_seconds] [output.mcap] [--accept-eula]

Defaults: 5 seconds → ../recordings/hands_<timestamp>.mcap

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import argparse
import contextlib
import sys
import time
from datetime import datetime
from pathlib import Path

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.deviceio import McapRecordingConfig
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from common import build_hand_pipeline


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "duration", nargs="?", type=float, default=5.0, help="Recording duration (s)"
    )
    parser.add_argument("output", nargs="?", help="Output .mcap path")
    parser.add_argument(
        "--accept-eula",
        action="store_true",
        help="Accept the NVIDIA CloudXR EULA non-interactively",
    )
    parser.add_argument(
        "--install-dir",
        default="~/.cloudxr",
        help="CloudXR install directory (default: ~/.cloudxr)",
    )
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).parent / "default.env"),
        help="Path to a KEY=value env file for CloudXR overrides (default: default.env)",
    )
    parser.add_argument(
        "--launch-cloudxr-runtime",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Launch the CloudXR runtime automatically (default: true; pass "
        "--no-launch-cloudxr-runtime to connect to the system runtime instead)",
    )
    args = parser.parse_args(argv[1:])

    duration_s: float = args.duration

    if args.output:
        mcap_path = Path(args.output)
        mcap_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(__file__).resolve().parent.parent / "recordings"
        out_dir.mkdir(exist_ok=True)
        mcap_path = out_dir / f"hands_{datetime.now():%Y%m%d_%H%M%S}.mcap"

    print(f"[record] writing {mcap_path} for {duration_s:.1f}s")

    config = TeleopSessionConfig(
        app_name="McapHandRecordExample",
        pipeline=build_hand_pipeline(),
        mcap_config=McapRecordingConfig(str(mcap_path)),
    )

    launcher_ctx = (
        contextlib.nullcontext()
        if not args.launch_cloudxr_runtime
        else CloudXRLauncher(
            install_dir=args.install_dir,
            env_config=args.env_file,
            accept_eula=args.accept_eula,
        )
    )
    with launcher_ctx as launcher:
        if launcher is not None:
            print(
                f"[record] CloudXR runtime started (WSS log: {launcher.wss_log_path})"
            )
        with TeleopSession(config) as session:
            start = time.time()
            while time.time() - start < duration_s:
                result = session.step()
                if session.frame_count % 60 == 0:
                    left = bool(result["left_valid"][0])
                    right = bool(result["right_valid"][0])
                    print(
                        f"[record] t={time.time() - start:5.2f}s  "
                        f"frame={session.frame_count}  L={'Y' if left else '-'} "
                        f"R={'Y' if right else '-'}"
                    )
                time.sleep(1 / 60)

    print(f"[record] done — {mcap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
