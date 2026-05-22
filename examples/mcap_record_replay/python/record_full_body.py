# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Record a live OpenXR full-body tracking session to an MCAP file.

Requires an active OpenXR runtime / headset. The pipeline in ``common.py``
wires ``FullBodySource`` and ``ControllersSource``, so ``TeleopSession``
records the ``full_body`` and ``controllers`` channels.

Usage:
    python record_full_body.py [duration_seconds] [output.mcap]

Defaults: 5 seconds → ../recordings/full_body_<timestamp>.mcap

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from isaacteleop.deviceio import McapRecordingConfig
from isaacteleop.retargeting_engine.tensor_types.indices import FullBodyInputIndex
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from common import BODY_JOINT_NAMES, build_full_body_pipeline


def main(argv: list[str]) -> int:
    duration_s = float(argv[1]) if len(argv) > 1 else 5.0

    if len(argv) > 2:
        mcap_path = Path(argv[2])
        mcap_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(__file__).resolve().parent.parent / "recordings"
        out_dir.mkdir(exist_ok=True)
        mcap_path = out_dir / f"full_body_{datetime.now():%Y%m%d_%H%M%S}.mcap"

    print(f"[record] writing {mcap_path} for {duration_s:.1f}s")

    config = TeleopSessionConfig(
        app_name="McapFullBodyRecordExample",
        pipeline=build_full_body_pipeline(),
        mcap_config=McapRecordingConfig(str(mcap_path)),
    )

    with TeleopSession(config) as session:
        start = time.time()
        while time.time() - start < duration_s:
            result = session.step()
            if session.frame_count % 60 == 0:
                full_body = result["full_body"]
                n_valid = (
                    0
                    if full_body.is_none
                    else int(
                        np.count_nonzero(
                            np.asarray(
                                full_body[FullBodyInputIndex.JOINT_VALID],
                                dtype=np.uint8,
                            )
                        )
                    )
                )
                print(
                    f"[record] t={time.time() - start:5.2f}s  "
                    f"frame={session.frame_count}  "
                    f"joints={n_valid:02d}/{len(BODY_JOINT_NAMES)}"
                )
            time.sleep(1 / 60)

    print(f"[record] done — {mcap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
