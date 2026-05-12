# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Record a live OpenXR hand-tracking session to an MCAP file.

Requires an active OpenXR runtime / headset. The pipeline in ``common.py``
wires only ``HandsSource``, so ``TeleopSession`` records exactly the ``hands``
channel — no head, no controllers.

Usage:
    python record_hand.py [duration_seconds] [output.mcap]

Defaults: 5 seconds → ../recordings/hands_<timestamp>.mcap

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from isaacteleop.deviceio import McapRecordingConfig
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from common import build_pipeline


def main(argv: list[str]) -> int:
    duration_s = float(argv[1]) if len(argv) > 1 else 5.0

    if len(argv) > 2:
        mcap_path = Path(argv[2])
        mcap_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(__file__).resolve().parent.parent / "recordings"
        out_dir.mkdir(exist_ok=True)
        mcap_path = out_dir / f"hands_{datetime.now():%Y%m%d_%H%M%S}.mcap"

    print(f"[record] writing {mcap_path} for {duration_s:.1f}s")

    config = TeleopSessionConfig(
        app_name="McapHandRecordExample",
        pipeline=build_pipeline(),
        mcap_config=McapRecordingConfig(str(mcap_path)),
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
