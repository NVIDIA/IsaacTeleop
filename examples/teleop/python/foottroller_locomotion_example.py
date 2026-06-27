# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Foottroller Locomotion Example.

Demonstrates using FoottrollerRootCmdRetargeter to generate robot base commands
from a Foottroller. Requires foottroller data to
be pushed to OpenXR
"""

import sys
import time
from pathlib import Path

from isaacteleop.retargeters import (
    FoottrollerRootCmdRetargeter,
    FoottrollerRootCmdRetargeterConfig,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import FoottrollerSource
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    PluginConfig,
)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


def main():
    print("\n" + "=" * 80)
    print("  Foottroller Locomotion Example")
    print("=" * 80)
    print("Controls (foottroller):")
    print("=" * 80)
    print("Note: Run Foottroller plugin so Foottroller data is available.")
    print("=" * 80 + "\n")

    # ==================================================================
    # Setup: Create foottroller source
    # ==================================================================
    Foottroller_source = FoottrollerSource(name="foottroller")

    # ==================================================================
    # Build Retargeting Pipeline
    # ==================================================================

    config = FoottrollerRootCmdRetargeterConfig(
        mode="horizontal",
    )

    foottroller_retargeter = FoottrollerRootCmdRetargeter(config, name="foottroller")

    pipeline = foottroller_retargeter.connect(
        {
            "foottroller": Foottroller_source.output("foottroller"),
        }
    )

    # ==================================================================
    # Configure Plugins (optional)
    # ==================================================================

    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(
            PluginConfig(
                plugin_name=PLUGIN_NAME,
                plugin_root_id=PLUGIN_ROOT_ID,
                search_paths=[PLUGIN_ROOT_DIR],
            )
        )

    # ==================================================================
    # Create and run TeleopSession
    # ==================================================================

    session_config = TeleopSessionConfig(
        app_name="FoottrollerLocomotionExample",
        trackers=[],
        pipeline=pipeline,
        plugins=plugins,
    )

    with TeleopSession(session_config) as session:
        start_time = time.time()

        while time.time() - start_time < 100.0:
            result = session.step()

            # Get root command: [vel_x, vel_y, rot_vel_z, hip_height]
            cmd = result["root_command"][0]

            elapsed = session.get_elapsed_time()
            print(
                f"[{elapsed:5.1f}s] Vel: ({cmd[0]:5.2f}, {cmd[1]:5.2f})  "
                f"Rot: {cmd[2]:5.2f}  Height: {cmd[3]:.3f}",
                end="\r",
                flush=True,
            )

            time.sleep(0.01)  # ~100 FPS

        print("\nTime limit reached.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
