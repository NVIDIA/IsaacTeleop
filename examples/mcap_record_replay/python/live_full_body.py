# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Visualize live OpenXR full-body pose tracking in real time with viser.

``CloudXRLauncher`` starts the CloudXR runtime and WSS proxy automatically.
Open the URL viser prints (default http://localhost:8080) in a browser to see
the full PICO body skeleton — joints colored green when valid, red when lost —
updating live as you move.

Usage:
    python live_full_body.py [--port 8080] [--host 127.0.0.1] [--accept-eula]

Press Ctrl+C to stop.

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import argparse
import contextlib
import sys
import time
from pathlib import Path

import numpy as np
import viser

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.tensor_types.indices import FullBodyInputIndex
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from common import BODY_JOINT_NAMES, FullBodyViz, build_full_body_pipeline


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Viser HTTP bind address (default: 127.0.0.1; pass 0.0.0.0 to expose externally)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Viser HTTP port")
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

    server = viser.ViserServer(host=args.host, port=args.port)
    server.scene.set_up_direction("+y")
    server.scene.add_grid(name="/grid", width=2.0, height=2.0, cell_size=0.1)

    config = TeleopSessionConfig(
        app_name="LiveFullBodyExample",
        pipeline=build_full_body_pipeline(),
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
            print(f"[live] CloudXR runtime started (WSS log: {launcher.wss_log_path})")
        print("[live] waiting for headset connection… (Ctrl+C to stop)")

        with TeleopSession(config) as session:
            viz = FullBodyViz(server)
            print(f"[live] viser running at http://localhost:{args.port}")
            try:
                while True:
                    result = session.step()
                    full_body = result["full_body"]

                    if full_body.is_none:
                        viz.update(None, None)
                        n_valid = 0
                    else:
                        positions = np.asarray(
                            full_body[FullBodyInputIndex.JOINT_POSITIONS],
                            dtype=np.float32,
                        )
                        valid = np.asarray(
                            full_body[FullBodyInputIndex.JOINT_VALID], dtype=np.uint8
                        )
                        viz.update(positions, valid)
                        n_valid = int(np.count_nonzero(valid))

                    if session.frame_count % 60 == 0:
                        print(
                            f"[live] frame={session.frame_count}  "
                            f"joints={n_valid:02d}/{len(BODY_JOINT_NAMES)}"
                        )
                    time.sleep(1 / 60)
            except KeyboardInterrupt:
                pass

    print("[live] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
