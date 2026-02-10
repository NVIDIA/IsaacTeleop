#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test OAK-D camera plugin using Plugin Manager with FrameMetadataTrackerOakD and MCAP recording.

This test:
1. Uses PluginManager to discover and launch the camera plugin
2. Queries available devices from the manifest
3. Starts the OAK-D camera plugin (which records H.264 video to file)
4. Creates FrameMetadataTrackerOakD to receive frame metadata via OpenXR tensor extensions
5. Records frame metadata to MCAP file for playback/analysis
6. Periodically polls plugin health

Note: Plugin crashes will raise pm.PluginCrashException
      By default, video is saved to the plugin's working directory under ./recordings/
      MCAP file is saved in the current directory with timestamped filename.
"""

import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import isaacteleop.plugin_manager as pm
import isaacteleop.deviceio as deviceio
import isaacteleop.mcap as mcap
import isaacteleop.oxr as oxr

# Paths
# The test will look for plugins in the install directory relative to this script
# This script is in install/examples/oxr/python
# Plugins are in install/plugins
PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


def run_test(duration: float = 10.0, metadata_track: bool = True):
    print("=" * 80)
    title = "OAK-D Camera Plugin Test"
    if metadata_track:
        title += " with FrameMetadataTrackerOakD + MCAP Recording"
    print(title)
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

    # 3. Create FrameMetadataTrackerOakD (optional)
    frame_tracker = None
    trackers = []
    required_extensions = []
    mcap_filename = None

    if metadata_track:
        print("[Step 3] Creating FrameMetadataTrackerOakD...")
        # The collection_id must match the plugin_root_id used by the camera plugin
        frame_tracker = deviceio.FrameMetadataTrackerOakD(plugin_root_id)
        trackers = [frame_tracker]
        required_extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
        print(f"  ✓ Created {frame_tracker.get_name()} (collection_id: {plugin_root_id})")
        print()
        print("[Step 4] Getting required OpenXR extensions...")
        print(f"  ✓ Required extensions: {required_extensions}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mcap_filename = f"camera_metadata_{timestamp}.mcap"
    else:
        print("[Step 3] Skipping FrameMetadataTrackerOakD (--no-metadata)")
        print()

    # 5. Start Plugin and OpenXR session (if metadata tracking)
    print("[Step 5] Starting camera plugin...")
    print(f"  Plugin root ID: {plugin_root_id}")
    print(f"  Recording duration: {duration} seconds")
    if metadata_track:
        print(f"  MCAP output: {mcap_filename}")
    print()
    print("  Note: Video will be recorded to ./recordings/ in the plugin directory")
    if metadata_track:
        print("        Frame metadata will be recorded to MCAP file")
    print()

    with manager.start(plugin_name, plugin_root_id) as plugin:
        print("  ✓ Camera plugin started")

        if metadata_track:
            # Create OpenXR session for receiving metadata
            with oxr.OpenXRSession("OakDCameraTest", required_extensions) as oxr_session:
                handles = oxr_session.get_handles()
                print("  ✓ OpenXR session created")

                # Create DeviceIOSession with the tracker
                with deviceio.DeviceIOSession.run(trackers, handles) as session:
                    print("  ✓ DeviceIO session initialized")

                    # Create MCAP recorder
                    with mcap.McapRecorder.create(mcap_filename, [
                        (frame_tracker, "camera_metadata"),
                    ]) as recorder:
                        print("  ✓ MCAP recording started")
                        print()

                        # 6. Main tracking loop
                        print(f"[Step 6] Recording video and metadata ({duration} seconds)...")
                        print("-" * 80)
                        start_time = time.time()
                        frame_count = 0
                        last_print_time = 0
                        last_seq = -1
                        metadata_samples = 0

                        while time.time() - start_time < duration:
                            plugin.check_health()
                            if not session.update():
                                print("  Warning: Session update failed")
                                continue
                            recorder.record(session)
                            frame_count += 1
                            metadata = frame_tracker.get_data(session)
                            if metadata.timestamp and metadata.sequence_number != last_seq:
                                metadata_samples += 1
                                last_seq = metadata.sequence_number
                            elapsed = time.time() - start_time
                            if int(elapsed) > last_print_time:
                                last_print_time = int(elapsed)
                                ts_info = ""
                                if metadata.timestamp:
                                    ts_info = f"seq={metadata.sequence_number}, device_time={metadata.timestamp.device_time}"
                                else:
                                    ts_info = f"seq={metadata.sequence_number}, timestamp=None"
                                print(f"  [{last_print_time:3d}s] metadata_samples={metadata_samples}, {ts_info}")
                            time.sleep(0.016)

                        print("-" * 80)
                        print()
                        print(f"  ✓ Recording completed ({duration:.1f} seconds)")
                        print(f"  ✓ Processed {frame_count} update cycles")
                        print(f"  ✓ Received {metadata_samples} metadata samples")
        else:
            # Video-only mode: just run plugin for duration
            print()
            print(f"[Step 6] Recording video ({duration} seconds)...")
            print("-" * 80)
            start_time = time.time()
            last_print_time = 0
            while time.time() - start_time < duration:
                plugin.check_health()
                elapsed = time.time() - start_time
                if int(elapsed) > last_print_time:
                    last_print_time = int(elapsed)
                    print(f"  [{last_print_time:3d}s] Recording...")
                time.sleep(0.1)
            print("-" * 80)
            print()
            print(f"  ✓ Recording completed ({duration:.1f} seconds)")

    print()
    print("=" * 80)
    print("Test completed successfully!")
    print(f"  Video: {PLUGIN_ROOT_DIR / 'oakd_camera' / 'recordings'}")
    if metadata_track:
        print(f"  MCAP:  {Path.cwd() / mcap_filename}")
        print()
        print("View MCAP file with: foxglove-studio or mcap cat " + mcap_filename)
    print("=" * 80)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Test OAK-D camera plugin. By default uses FrameMetadataTrackerOakD and MCAP recording; use --no-metadata for video only."
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=10.0,
        help="Recording duration in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Disable metadata tracking and MCAP recording (video only)",
    )
    args = parser.parse_args()

    success = run_test(duration=args.duration, metadata_track=not args.no_metadata)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()



