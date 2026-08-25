# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SpaceMouse Printer Example.

Prints the translation axes, rotation axes, and every currently-held button each
frame, via SpaceMouseSource's "spacemouse_translation", "spacemouse_rotation", and
"spacemouse_buttons" outputs. Carries no semantic mapping (a position delta, a
rotation delta, a gripper toggle) -- that belongs in a retargeter (e.g.
SpaceMouseToSe3RelRetargeter) consuming this source's output. The spacemouse plugin
self-discovers its device and is auto-launched by TeleopSession -- no external
process to start manually.
"""

import sys
import time
from pathlib import Path

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.deviceio_source_nodes import SpaceMouseSource
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    PluginConfig,
)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "spacemouse"
PLUGIN_ROOT_ID = "spacemouse"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  SpaceMouse Printer Example")
    print("=" * 80)
    print("Move or twist the connected SpaceMouse, or press a button.")
    print("=" * 80 + "\n")

    # ==================================================================
    # Setup: Create spacemouse source
    # ==================================================================
    spacemouse_source = SpaceMouseSource(name="spacemouse")

    # ==================================================================
    # Configure Plugins
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
        app_name="SpaceMousePrinterExample",
        trackers=[],
        pipeline=spacemouse_source,
        plugins=plugins,
    )

    with CloudXRLauncher.launch_context(args):
        with TeleopSession(session_config) as session:
            start_time = time.time()
            prev_pressed: set[int] = set()

            while time.time() - start_time < 30.0:
                result = session.step()
                translation_group = result["spacemouse_translation"]
                rotation_group = result["spacemouse_rotation"]
                buttons_group = result["spacemouse_buttons"]

                elapsed = session.get_elapsed_time()
                if translation_group.is_none:
                    print(
                        f"[{elapsed:5.1f}s] (no spacemouse data yet)",
                        end="\r",
                        flush=True,
                    )
                    time.sleep(0.01)
                    continue

                translation = translation_group[0]
                rotation = rotation_group[0]
                bitmap = buttons_group[0]
                pressed = {code for code in range(len(bitmap)) if bitmap[code]}

                t_str = " ".join(f"{v:+.2f}" for v in translation)
                r_str = " ".join(f"{v:+.2f}" for v in rotation)

                # Live status line (overwritten each frame).
                names = [f"btn{code}" for code in sorted(pressed)]
                print(
                    f"[{elapsed:5.1f}s] T: [{t_str}]  R: [{r_str}]  Held: {' '.join(names) or '-'}"
                    + " " * 20,
                    end="\r",
                    flush=True,
                )

                # Permanent, scrollable log of every press/release transition -- a
                # quick tap can flash by on the status line above before you notice
                # it, but every transition is logged here.
                for code in sorted(pressed - prev_pressed):
                    print(f"[{elapsed:5.1f}s] btn{code} down")
                for code in sorted(prev_pressed - pressed):
                    print(f"[{elapsed:5.1f}s] btn{code} up")
                prev_pressed = pressed

                time.sleep(0.01)  # ~100 FPS

            print("\nTime limit reached.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
