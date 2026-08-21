# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard Printer Example.

Prints raw keyboard press state (W/A/S/D/Q/E/Z/X/T/G/C/V/K) each frame. The
keyboard plugin self-discovers its device and is auto-launched by
TeleopSession -- no external process to start manually.
"""

import sys
import time
from pathlib import Path

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.deviceio_source_nodes import KeyboardSource
from isaacteleop.retargeting_engine.tensor_types import KeyboardInputIndex
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    PluginConfig,
)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "keyboard"
PLUGIN_ROOT_ID = "keyboard"

_PRINT_KEYS = [
    ("W", KeyboardInputIndex.KEY_W),
    ("A", KeyboardInputIndex.KEY_A),
    ("S", KeyboardInputIndex.KEY_S),
    ("D", KeyboardInputIndex.KEY_D),
    ("Q", KeyboardInputIndex.KEY_Q),
    ("E", KeyboardInputIndex.KEY_E),
    ("Z", KeyboardInputIndex.KEY_Z),
    ("X", KeyboardInputIndex.KEY_X),
    ("T", KeyboardInputIndex.KEY_T),
    ("G", KeyboardInputIndex.KEY_G),
    ("C", KeyboardInputIndex.KEY_C),
    ("V", KeyboardInputIndex.KEY_V),
    ("K", KeyboardInputIndex.KEY_K),
]


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  Keyboard Printer Example")
    print("=" * 80)
    print("Press W/A/S/D/Q/E/Z/X/T/G/C/V/K on the machine running this example.")
    print("=" * 80 + "\n")

    # ==================================================================
    # Setup: Create keyboard source
    # ==================================================================
    keyboard_source = KeyboardSource(name="keyboard")

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
        app_name="KeyboardPrinterExample",
        trackers=[],
        pipeline=keyboard_source,
        plugins=plugins,
    )

    with CloudXRLauncher.launch_context(args):
        with TeleopSession(session_config) as session:
            start_time = time.time()
            prev_pressed: set[str] = set()

            while time.time() - start_time < 30.0:
                result = session.step()
                keys = result["keyboard"]

                elapsed = session.get_elapsed_time()
                if keys.is_none:
                    print(
                        f"[{elapsed:5.1f}s] (no keyboard data yet)",
                        end="\r",
                        flush=True,
                    )
                    time.sleep(0.01)
                    continue

                pressed = {name for name, index in _PRINT_KEYS if bool(keys[index])}

                # Live status line (overwritten each frame).
                print(
                    f"[{elapsed:5.1f}s] Held: {' '.join(sorted(pressed)) or '-'}"
                    + " " * 20,
                    end="\r",
                    flush=True,
                )

                # Permanent, scrollable log of every press/release transition -- a
                # quick tap can flash by on the status line above before you notice
                # it, but every transition is logged here.
                for name in sorted(pressed - prev_pressed):
                    print(f"[{elapsed:5.1f}s] {name} down")
                for name in sorted(prev_pressed - pressed):
                    print(f"[{elapsed:5.1f}s] {name} up")
                prev_pressed = pressed

                time.sleep(0.01)  # ~100 FPS

            print("\nTime limit reached.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
