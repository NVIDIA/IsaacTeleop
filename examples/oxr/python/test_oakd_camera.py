#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test OAK-D camera plugin using Plugin Manager.

This test:
1. Uses PluginManager to discover and launch the camera plugin
2. Queries available devices from the manifest
3. Starts the OAK-D camera plugin (which records H.264 video to MP4)
4. Periodically polls plugin health
5. Records video for a specified duration

Note: Plugin crashes will raise pm.PluginCrashException
      By default, video is saved to the plugin's working directory under ./recordings/
"""

import sys
import time
import argparse
from pathlib import Path

import teleopcore.plugin_manager as pm

# Paths
# The test will look for plugins in the install directory relative to this script
# This script is in install/examples/oxr/python
# Plugins are in install/plugins
PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


def run_test(duration: float = 10.0):
    print("=" * 80)
    print("OAK-D Camera Plugin Test")
    print("=" * 80)
    print()

    if not PLUGIN_ROOT_DIR.exists():
        print(f"Error: Plugin directory not found at {PLUGIN_ROOT_DIR}")
        print("Please build and install the project first.")
        return False

    # 1. Initialize Plugin Manager
    print("[Step 1] Initializing Plugin Manager...")
    print(f"  Search path: {PLUGIN_ROOT_DIR}")
    manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])

    plugins = manager.get_plugin_names()
    print(f"  Discovered plugins: {plugins}")

    plugin_name = "oakd_camera"
    plugin_root_id = "oakd_camera"

    if plugin_name not in plugins:
        print(f"  ✗ {plugin_name} plugin not found")
        print("  Available plugins:", plugins)
        return False

    print(f"  ✓ Found {plugin_name} plugin")
    print()

    # 2. Query Plugin Devices
    print("[Step 2] Querying plugin devices...")
    devices = manager.query_devices(plugin_name)
    print(f"  ✓ Available devices: {devices}")
    print()

    # 3. Start Plugin
    print("[Step 3] Starting camera plugin...")
    print(f"  Plugin root ID: {plugin_root_id}")
    print(f"  Recording duration: {duration} seconds")
    print()
    print("  Note: Video will be recorded to ./recordings/ in the plugin directory")
    print()

    try:
        with manager.start(plugin_name, plugin_root_id) as plugin:
            print("  ✓ Plugin started")
            print()

            # 4. Monitor plugin and wait for recording
            print(f"[Step 4] Recording video ({duration} seconds)...")
            start_time = time.time()
            check_count = 0

            while time.time() - start_time < duration:
                # Poll plugin health every ~1 second
                elapsed = time.time() - start_time
                if int(elapsed) > check_count:
                    check_count = int(elapsed)
                    try:
                        plugin.check_health()
                        print(f"  [{check_count:3d}s] Plugin healthy, recording...")
                    except pm.PluginCrashException as e:
                        print(f"  ✗ Plugin crashed: {e}")
                        return False

                time.sleep(0.1)

            print()
            print(f"  ✓ Recording completed ({duration:.1f} seconds)")

    except pm.PluginCrashException as e:
        print(f"  ✗ Plugin crashed during shutdown: {e}")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

    # Plugin automatically stopped when exiting 'with' block
    print()
    print("[Cleanup]")
    print("  ✓ Plugin stopped")
    print()
    print("=" * 80)
    print("Test completed successfully!")
    print(f"Check {PLUGIN_ROOT_DIR / 'oakd_camera' / 'recordings'} for the recorded video.")
    print("=" * 80)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Test OAK-D camera plugin - records video from OAK-D camera"
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=10.0,
        help="Recording duration in seconds (default: 10.0)",
    )
    args = parser.parse_args()

    success = run_test(duration=args.duration)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()



