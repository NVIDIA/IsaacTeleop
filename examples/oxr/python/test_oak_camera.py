#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test OAK camera plugin with Color + MonoLeft streams, metadata tracking, and MCAP recording.

Supports three metadata modes (--mode):
  no-metadata    Video-only, no metadata tracking.
  schema-pusher  Metadata pushed via OpenXR tensor extensions, read by
                 FrameMetadataTrackerOak on the host, recorded to MCAP by the host.
  plugin-mcap    Plugin writes per-stream FrameMetadataOak directly to a local MCAP file.

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

PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"

MODE_NO_METADATA = "no-metadata"
MODE_SCHEMA_PUSHER = "schema-pusher"
MODE_PLUGIN_MCAP = "plugin-mcap"


def _run_recording_loop(plugin, duration: float):
    """Run the plugin for the given duration, only monitoring health."""
    print()
    print(f"[Step 6] Recording ({duration} seconds)...")
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
    print(f"  Recording completed ({duration:.1f} seconds)")


def _run_schema_pusher(
    plugin,
    duration: float,
    tracker,
    stream_names: list[str],
    required_extensions: list[str],
    mcap_filename: str,
):
    """Read metadata via OpenXR schema tracker and record to MCAP on the host side."""
    with oxr.OpenXRSession("OakCameraTest", required_extensions) as oxr_session:
        handles = oxr_session.get_handles()
        print("  ✓ OpenXR session created")

        # Create DeviceIOSession with all trackers
        with deviceio.DeviceIOSession.run([tracker], handles) as session:
            print("  ✓ DeviceIO session initialized")

            # Create MCAP recorder with per-stream FrameMetadataOak channels
            mcap_entries = [(tracker, "oak_metadata")]
            with mcap.McapRecorder.create(
                mcap_filename,
                mcap_entries,
            ) as recorder:
                print("  ✓ MCAP recording started")
                print()

                # 6. Main tracking loop
                print(f"[Step 6] Recording video and metadata ({duration} seconds)...")
                print("-" * 80)
                start_time = time.time()
                frame_count = 0
                last_print_time = 0
                last_seq = dict.fromkeys(stream_names, -1)
                metadata_samples = dict.fromkeys(stream_names, 0)

                while time.time() - start_time < duration:
                    plugin.check_health()
                    if not session.update():
                        print("  Warning: Session update failed")
                        continue
                    recorder.record(session)
                    frame_count += 1

                    elapsed = time.time() - start_time
                    for idx, name in enumerate(stream_names):
                        tracked = tracker.get_stream_data(session, idx)
                        if (
                            tracked.data is not None
                            and tracked.data.sequence_number != last_seq.get(name, -1)
                        ):
                            metadata_samples[name] = metadata_samples.get(name, 0) + 1
                            last_seq[name] = tracked.data.sequence_number

                    if int(elapsed) > last_print_time:
                        last_print_time = int(elapsed)
                        parts = []
                        for name in stream_names:
                            parts.append(f"{name}={metadata_samples.get(name, 0)}")
                        print(f"  [{last_print_time:3d}s] samples: {', '.join(parts)}")
                    time.sleep(0.016)

                print("-" * 80)
                print()
                print(f"  ✓ Recording completed ({duration:.1f} seconds)")
                print(f"  ✓ Processed {frame_count} update cycles")
                for name in stream_names:
                    print(
                        f"  ✓ {name}: {metadata_samples.get(name, 0)} metadata samples"
                    )


def run_test(duration: float = 10.0, mode: str = MODE_NO_METADATA):
    print("=" * 80)
    print(f"OAK Camera Plugin Test  [mode: {mode}]")
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

    plugin_name = "oak_camera"
    plugin_root_id = "oak_camera"

    if plugin_name not in plugins:
        print(f"  {plugin_name} plugin not found")
        print("  Available plugins:", plugins)
        return False

    print(f"  Found {plugin_name} plugin")
    print()

    # 2. Query Plugin Devices
    print("[Step 2] Querying plugin devices...")
    devices = manager.query_devices(plugin_name)
    print(f"  Available devices: {devices}")
    print()

    # 3. Prepare mode-specific state
    stream_names = ["Color", "MonoLeft"]
    stream_types = [deviceio.StreamType.Color, deviceio.StreamType.MonoLeft]
    collection_prefix = "oak_camera"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mcap_filename = f"camera_metadata_{timestamp}.mcap"

    tracker = None
    required_extensions = []

    if mode == MODE_SCHEMA_PUSHER:
        print("[Step 3] Creating composite FrameMetadataTrackerOak...")
        tracker = deviceio.FrameMetadataTrackerOak(collection_prefix, stream_types)
        print(
            f"  Created tracker (prefix: {collection_prefix}, streams: {stream_names})"
        )
        required_extensions = deviceio.DeviceIOSession.get_required_extensions(
            [tracker]
        )
        print()
        print("[Step 4] Getting required OpenXR extensions...")
        print(f"  Required extensions: {required_extensions}")
    elif mode == MODE_PLUGIN_MCAP:
        print("[Step 3] Plugin will record MCAP directly (no host-side tracker)")
        print(f"  MCAP output: {Path.cwd() / mcap_filename}")
    else:
        print("[Step 3] No metadata tracking")
    print()

    # 4. Build plugin arguments
    color_path = f"./recordings/color_{timestamp}.h264"
    mono_left_path = f"./recordings/mono_left_{timestamp}.h264"
    extra_args = [
        f"--add-stream=camera=Color,output={color_path}",
        f"--add-stream=camera=MonoLeft,output={mono_left_path}",
    ]

    # For plugin-mcap, resolve to absolute path so the plugin can find it
    mcap_abs_path = str(Path.cwd() / mcap_filename)

    if mode == MODE_SCHEMA_PUSHER:
        extra_args.append(f"--collection-prefix={collection_prefix}")
    elif mode == MODE_PLUGIN_MCAP:
        extra_args.append(f"--mcap-filename={mcap_abs_path}")

    # 5. Start Plugin
    print("[Step 5] Starting camera plugin...")
    print(f"  Plugin root ID: {plugin_root_id}")
    print(f"  Mode: {mode}")
    print(f"  Recording duration: {duration} seconds")
    print()

    with manager.start(plugin_name, plugin_root_id, extra_args) as plugin:
        print("  Camera plugin started")

        if mode == MODE_SCHEMA_PUSHER:
            _run_schema_pusher(
                plugin,
                duration,
                tracker,
                stream_names,
                required_extensions,
                mcap_filename,
            )
        else:
            _run_recording_loop(plugin, duration)

    print()
    print("=" * 80)
    print("Test completed successfully!")
    recordings_dir = PLUGIN_ROOT_DIR / "oak_camera" / "recordings"
    print(f"  Color H.264:    {recordings_dir / Path(color_path).name}")
    print(f"  MonoLeft H.264: {recordings_dir / Path(mono_left_path).name}")
    if mode in (MODE_SCHEMA_PUSHER, MODE_PLUGIN_MCAP):
        mcap_display = mcap_abs_path if mode == MODE_PLUGIN_MCAP else mcap_filename
        print(f"  MCAP:           {Path(mcap_display).resolve()}")
        print()
        print(f"View MCAP file with: foxglove-studio or mcap cat {mcap_display}")
    print("=" * 80)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Test OAK camera plugin with three metadata modes."
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=10.0,
        help="Recording duration in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--mode",
        choices=[MODE_NO_METADATA, MODE_SCHEMA_PUSHER, MODE_PLUGIN_MCAP],
        default=MODE_NO_METADATA,
        help="Metadata mode (default: schema-pusher)",
    )
    args = parser.parse_args()

    success = run_test(duration=args.duration, mode=args.mode)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
