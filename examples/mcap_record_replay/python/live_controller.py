# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Visualize live OpenXR controller poses in real time with viser.

``CloudXRLauncher`` starts the CloudXR runtime and WSS proxy automatically.
Open the URL viser prints (default http://localhost:8080) in a browser to see
aim / grip points for both controllers, a ray between them, and a live HUD
showing thumbstick, trigger, squeeze, and button state.

Usage:
    python live_controller.py [--port 8080] [--host 127.0.0.1] [--accept-eula]

Press Ctrl+C to stop.

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import argparse
import sys
import time

import viser

from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

from common import (
    ControllerViz,
    LEFT_COLOR,
    RIGHT_COLOR,
    add_cloudxr_arguments,
    build_controller_pipeline,
    cloudxr_launch_context,
    controller_state,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Viser HTTP bind address (default: 127.0.0.1; pass 0.0.0.0 to expose externally)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Viser HTTP port")
    add_cloudxr_arguments(parser)
    args = parser.parse_args(argv[1:])

    server = viser.ViserServer(host=args.host, port=args.port)
    server.scene.set_up_direction("+y")
    server.scene.add_grid(name="/grid", width=2.0, height=2.0, cell_size=0.1)

    config = TeleopSessionConfig(
        app_name="LiveControllerExample",
        pipeline=build_controller_pipeline(),
    )

    with cloudxr_launch_context(args) as launcher:
        if launcher is not None:
            print(f"[live] CloudXR runtime started (WSS log: {launcher.wss_log_path})")
        print("[live] waiting for headset connection… (Ctrl+C to stop)")

        with TeleopSession(config) as session:
            viz_left = ControllerViz(server, "controller_left", LEFT_COLOR)
            viz_right = ControllerViz(server, "controller_right", RIGHT_COLOR)
            print(f"[live] viser running at http://localhost:{args.port}")
            _last_step_t = time.time()
            _missed = 0
            try:
                while True:
                    now = time.time()
                    _missed += max(0, round((now - _last_step_t) * 60) - 1)
                    _last_step_t = now

                    result = session.step()

                    l_state = controller_state(result["controller_left"])
                    r_state = controller_state(result["controller_right"])

                    viz_left.update(l_state)
                    viz_right.update(r_state)

                    if session.frame_count % 60 == 0:
                        print(
                            f"[live] frame={session.frame_count}  "
                            f"L={'Y' if l_state['aim_valid'] else '-'}  "
                            f"R={'Y' if r_state['aim_valid'] else '-'}  "
                            f"missed={_missed}"
                        )
                        _missed = 0
                    time.sleep(1 / 60)
            except KeyboardInterrupt:
                pass

    print("[live] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
