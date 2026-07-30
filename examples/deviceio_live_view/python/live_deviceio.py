# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Visualize live DeviceIO human tracking in real time with viser.

Registers every human-related DeviceIO source (hands, head, controllers, full
body) and draws whichever trackers are currently active. Inactive or absent
trackers are hidden rather than shown in an error color.

``CloudXRLauncher`` starts the CloudXR runtime and WSS proxy automatically.
Open the URL viser prints (default http://localhost:8080) in a browser.

Usage:
    python live_deviceio.py [--port 8080] [--host 127.0.0.1] [--accept-eula]

Press Ctrl+C to stop.
"""

import argparse
import sys
import time

import viser

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from deviceio_viser import (
    BODY_JOINT_NAMES,
    HumanDeviceIOViz,
    build_all_human_pipeline,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Viser HTTP bind address (default: 127.0.0.1; pass 0.0.0.0 to expose externally)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Viser HTTP port")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    server = viser.ViserServer(host=args.host, port=args.port)
    server.scene.set_up_direction("+y")
    server.scene.add_grid(name="/grid", width=2.0, height=2.0, cell_size=0.1)

    config = TeleopSessionConfig(
        app_name="LiveDeviceIOExample",
        pipeline=build_all_human_pipeline(),
    )

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher is not None:
            print(f"[live] CloudXR runtime started (WSS log: {launcher.wss_log_path})")
        print("[live] waiting for headset connection… (Ctrl+C to stop)")

        with TeleopSession(config) as session:
            viz = HumanDeviceIOViz(server)
            print(f"[live] viser running at http://localhost:{args.port}")
            try:
                while True:
                    result = session.step()
                    active = viz.update(result)

                    if session.frame_count % 60 == 0:
                        body_joints = active["full_body_joints"]
                        print(
                            f"[live] frame={session.frame_count}  "
                            f"hands(L/R)={'Y' if active['hand_left'] else '-'}/"
                            f"{'Y' if active['hand_right'] else '-'}  "
                            f"head={'Y' if active['head'] else '-'}  "
                            f"ctrl(L/R)={'Y' if active['controller_left'] else '-'}/"
                            f"{'Y' if active['controller_right'] else '-'}  "
                            f"body={body_joints:02d}/{len(BODY_JOINT_NAMES)}"
                        )
                    time.sleep(1 / 60)
            except KeyboardInterrupt:
                pass

    print("[live] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
