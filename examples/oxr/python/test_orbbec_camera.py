# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Record every Orbbec Ego data class in one of the three supported modes."""

import argparse
import time
from pathlib import Path

import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
import isaacteleop.plugin_manager as plugin_manager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=["no-metadata", "plugin-mcap", "schema-pusher"],
        default="schema-pusher",
    )
    parser.add_argument("--format", choices=["mjpg", "h264", "h265"], default="h264")
    parser.add_argument("--mcap", type=Path, default=Path("orbbec_ego.mcap"))
    args = parser.parse_args()

    prefix = "orbbec_ego"
    frame = deviceio.FrameMetadataTrackerOrbbec(
        prefix,
        [
            deviceio.OrbbecCameraStream.ColorLeft,
            deviceio.OrbbecCameraStream.ColorRight,
        ],
    )
    imu = deviceio.OrbbecImuTracker(prefix)
    audio = deviceio.OrbbecAudioTracker(prefix)
    calibration = deviceio.OrbbecCalibrationTracker(prefix)
    state = deviceio.OrbbecDeviceStateTracker(prefix)
    trackers = [frame, imu, audio, calibration, state]

    suffix = {"mjpg": "mjpg", "h264": "h264", "h265": "h265"}[args.format]
    plugin_args = [
        f"--add-stream=camera=ColorLeft,output=recordings/left.{suffix},format={args.format},width=1600,height=1300,fps=30",
        f"--add-stream=camera=ColorRight,output=recordings/right.{suffix},format={args.format},width=1600,height=1300,fps=30",
        "--enable-imu",
        "--imu-rate=1000",
        "--audio-output=recordings/audio.wav",
        "--calibration-output=recordings/calibration.json",
        "--preview",
    ]
    if args.mode == "plugin-mcap":
        plugin_args.append(f"--mcap-filename={args.mcap.resolve()}")
    elif args.mode == "schema-pusher":
        plugin_args.append(f"--collection-prefix={prefix}")

    manager = plugin_manager.PluginManager([str(args.plugin_root)])
    if "orbbec_camera" not in manager.get_plugin_names():
        raise RuntimeError("orbbec_camera plugin was not discovered")

    with manager.start("orbbec_camera", "orbbec_camera", plugin_args) as plugin:
        if args.mode != "schema-pusher":
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                plugin.check_health()
                time.sleep(0.1)
            return 0

        extensions = deviceio.DeviceIOSession.get_required_extensions(trackers)
        recording = deviceio.McapRecordingConfig(
            str(args.mcap),
            [
                (frame, "orbbec_metadata"),
                (imu, "orbbec_imu"),
                (audio, "orbbec_audio"),
                (calibration, "orbbec_calibration"),
                (state, "orbbec_device"),
            ],
        )
        with oxr.OpenXRSession("OrbbecCameraTest", extensions) as oxr_session:
            with deviceio.DeviceIOSession.run(
                trackers, oxr_session.get_handles(), recording
            ) as session:

                def all_data_received() -> bool:
                    return (
                        not any(
                            frame.get_stream_data(session, i).data is None
                            for i in range(2)
                        )
                        and not any(
                            imu.get_stream_data(session, i).data is None
                            for i in range(2)
                        )
                        and audio.get_data(session).data is not None
                        and calibration.get_data(session).data is not None
                        and state.get_data(session).data is not None
                    )

                startup_deadline = time.monotonic() + 30.0
                while not all_data_received() and time.monotonic() < startup_deadline:
                    plugin.check_health()
                    session.update()
                    time.sleep(0.016)
                if not all_data_received():
                    raise RuntimeError(
                        "did not receive all Orbbec data classes within 30 seconds"
                    )

                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    plugin.check_health()
                    session.update()
                    time.sleep(0.016)

                if not all_data_received():
                    raise RuntimeError("lost an Orbbec data class during recording")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
