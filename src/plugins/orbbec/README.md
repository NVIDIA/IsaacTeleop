<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Orbbec Ego Camera Plugin

This C++ Isaac Teleop plugin captures **capability-compatible Orbbec Ego** devices
sensor set: `ColorLeft`, `ColorRight`, accelerometer, gyroscope, and microphone.
It records elementary MJPEG/H.264/H.265 video, PCM WAV audio, and the structured
data required to synchronize those media files with Isaac Teleop MCAP recordings.

This is deliberately an Ego-specific plugin, not a claim that every Orbbec model
has the same sensors or profiles. Ego does **not** expose Depth or IR; D2C,
depth/IR images, and point clouds are therefore not implemented here.

## Features

- Dual ColorLeft/ColorRight raw video recording without a container.
- Per-stream MJPEG, H.264, or H.265 profile selection; per-stream dimensions and
  frame rate override global defaults.
- Latest-frame, timestamp-paired SDL stereo preview with persistent textures.
  MJPEG is decoded by OrbbecSDK; H.264/H.265 by FFmpeg. It is a convenience
  preview, not the latency-certified GPU path; use `camera_viz` for NVDEC.
- Frame metadata, IMU batches, WAV sample indices, calibration, and device state.
- Three recording modes: raw media only, plugin-local MCAP, or TeleopSession
  multi-device MCAP through OpenXR SchemaPushers.
- Ego controls: exposure, gain, white balance, image controls, anti-flicker,
  bitrate, dynamic bitrate, IMU ODR/range, calibration export, and temperature.
- Independent GPU-resident stereo source for `examples/camera_viz`.

## Prerequisites

### Hardware

- An Orbbec Ego with ColorLeft and/or ColorRight sensors and a USB data cable.
- The validated Ego PID `0x1201` enumerates as USB 2.0 (`bcdUSB 2.00` and
  `480M` in `lsusb -t`), including when connected to a USB 3.x host port. This
  is normal device behavior, not a cable or port downgrade. Use a direct,
  reliable data connection and choose only the profiles reported by
  `--list-capabilities`.
- A desktop session for `--preview`; it requires an available SDL display.

### Software

- Ubuntu 22.04 x86_64 is the validated host. A supported Linux build
  environment for Isaac Teleop needs CMake, a C++ compiler, Python, `uv`, and
  the dependencies required by the selected Isaac Teleop preset.
- OrbbecSDK v2 Linux x86_64 package. It is external to this repository and must
  contain `include/libobsensor/ObSensor.hpp`, `lib/OrbbecSDKConfig.cmake`,
  `lib/libOrbbecSDK.so.2`, and `lib/extensions/`.
- Preview build dependencies: `pkg-config`, SDL2 development files, and FFmpeg
  development files for `libavcodec`, `libavutil`, and `libswscale`. The
  installed executable also needs the matching SDL2/FFmpeg runtime libraries
  and `libjsoncpp` runtime library; verify them with `ldd` on the installed
  executable.

For Debian/Ubuntu the preview packages are normally:

```bash
sudo apt update
sudo apt install -y build-essential cmake libx11-dev clang-format-14 ccache patchelf \
  pkg-config libudev-dev libsdl2-dev libavcodec-dev libavutil-dev libswscale-dev \
  ffmpeg jq
```

Install the udev rules supplied by the selected OrbbecSDK package before relying
on non-root access. For the extracted v2 SDK used here, the package provides
`shared/install_udev_rules.sh`; run that release's script with `sudo`, reconnect
the camera, then verify access with `--list-capabilities`. Do not copy a rule
from another SDK release.

## Configure and build

From the IsaacTeleop repository root, point CMake to the extracted SDK package:

```bash
cmake --preset py3.11 -DBUILD_VIZ=OFF \
  -DBUILD_PLUGIN_ORBBEC_CAMERA=ON \
  -DORBBEC_SDK_ROOT=/absolute/path/to/OrbbecSDK_v2.9.0_linux_x86_64

cmake --build build/cmake-cpython-311 --target camera_plugin_orbbec --parallel
```

Ubuntu 22.04's packaged CMake is 3.22 and does not support `cmake --fresh`.
When switching SDKs, Python versions, or CMake options, remove only the generated
build directory before configuring again:

```bash
cmake -E rm -rf build/cmake-cpython-311
```

The build-tree executable is:

```bash
build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec --help
```

To install the plugin, including its manifest, SDK shared libraries, SDK
extensions, and this README:

```bash
cmake --install build/cmake-cpython-311 --prefix /absolute/path/to/isaacteleop-install
```

The installed plugin root is `plugins/orbbec_camera/`. Verify the installed
runtime dependencies before deployment:

```bash
ldd /absolute/path/to/isaacteleop-install/plugins/orbbec_camera/camera_plugin_orbbec
```

## Inspect the connected device first

Do not assume a profile or property range from another Ego firmware revision.
Ask the connected device:

```bash
build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec \
  --list-capabilities
```

The validated device exposes ColorLeft/ColorRight MJPEG/H.264/H.265 profiles,
Accel/Gyro profiles at 400/1000 Hz, PCM 48 kHz mono S16_LE audio, and the
properties listed later in this document. The command prints the exact profiles,
SDK property permissions, ranges, and integer steps for the connected device.

For brevity, the examples below use this shell variable:

```bash
export ORBBEC_PLUGIN="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec"
```

This is the complete initialization needed for the build-tree executable. It
has a build RPATH to the selected SDK, so do **not** add arbitrary SDK paths to
`LD_LIBRARY_PATH`. The variable exists only in the terminal where it is
assigned. In every new terminal, first `cd` to the repository root, run the
`export` above again, and verify it before a capture:

```bash
test -x "$ORBBEC_PLUGIN" || { echo "ORBBEC_PLUGIN is unset or invalid" >&2; exit 1; }
```

## Before every recording: terminal, directory, and clean stop

All relative output paths below are relative to the repository root. Create one
new, timestamped directory per run; this prevents a new elementary stream from
being confused with an earlier recording.

```bash
cd /absolute/path/to/IsaacTeleop
export ORBBEC_PLUGIN="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec"
test -x "$ORBBEC_PLUGIN" || { echo "Build the plugin first" >&2; exit 1; }

RUN="recordings/ego_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
echo "Recording directory: $RUN"
```

Keep the capture terminal open and stop the plugin with `Ctrl-C` once. Wait for
its final statistics and the shell prompt before inspecting files; this closes
the WAV/MCAP writers and flushes elementary video. To make a bounded automated
capture, use `timeout -s INT 20 ...`; status `124` is expected when `timeout`
sends that intentional SIGINT.

Each run has this layout when the corresponding options are used:

```text
<RUN>/raw/left.mjpg|h264|h265      elementary left video
<RUN>/raw/right.mjpg|h264|h265     elementary right video
<RUN>/ego.wav                      48 kHz mono S16_LE audio (optional)
<RUN>/calibration.json             structured calibration export (optional)
<RUN>/local.mcap                   metadata MCAP in local mode (optional)
<RUN>/teleop.mcap                  metadata plus other trackers in TeleopSession mode (optional)
<RUN>/logs/capture.log             terminal output and final counters
```

## Usage

Press `Ctrl-C` to stop a capture cleanly. The plugin finalizes WAV and MCAP output
on shutdown. Every capture needs at least one `--add-stream` argument.

### Recording-mode decision

Choose exactly one of these modes. In all three modes, video is always written
as separate `.mjpg`, `.h264`, or `.h265` files and optional audio is a separate
`.wav` file. MCAP intentionally stores time-synchronised structured data, **not**
the high-throughput video or PCM bytes.

| Mode | Plugin option | MCAP writer | Use it when |
|---|---|---|---|
| Raw media only | neither MCAP option | none | You only need video and/or WAV. |
| Local metadata MCAP | `--mcap-filename=<RUN>/local.mcap` | plugin | You need camera metadata, IMU, audio index, calibration, and state in one local file. |
| TeleopSession MCAP | `--collection-prefix=<prefix>` | Python DeviceIO/TeleopSession | You need the camera data in the **same** MCAP as hands, head, controllers, or other trackers. |

`--mcap-filename` and `--collection-prefix` are mutually exclusive. Supplying
both is an intentional startup error, not a way to obtain two MCAP files.

### 1. Record raw video only

This writes only elementary video; no MCAP is created.

```bash
RUN="recordings/ego_raw_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.mjpg" \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.mjpg" \
  2>&1 | tee "$RUN/logs/capture.log"
```

The default format is MJPEG and a zero/omitted width, height, or FPS lets the SDK
select a compatible profile. On successful clean shutdown, `capture.log` prints
nonzero frame and byte counts for both eyes. For an acceptance recording, its
last statistics must show `0 sequence gaps`, `video_frame_sets_dropped=0`, and
`dropped=0`.

### 2. Record explicit H.264 or H.265 profiles

`format`, `width`, `height`, and `fps` inside `--add-stream` take precedence over
the global `--width`, `--height`, and `--fps` defaults.

```bash
RUN="recordings/ego_h264_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.h264",format=h264,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.h264",format=h264,width=1600,height=1300,fps=30 \
  --bitrate=8 --dynamic-bitrate=on \
  2>&1 | tee "$RUN/logs/capture.log"
```

Use `format=h265` and `.h265` filenames for HEVC. `--bitrate` is passed as the
integer value of `OB_PROP_COLOR_BITRATE_INT`; it is **not** bits per second.
The validated Ego firmware reports an allowed range of `0..50`, but the exact
unit, range, and step are firmware-dependent. Always use a value printed by
`--list-capabilities`; `8` above is an example only. Start a new recording from
a keyframe; the plugin waits for required H.264/H.265 parameter sets before
writing an elementary stream so a file does not begin in the middle of a GOP.
If the SDK reports a compressed-frame sequence gap, the plugin reports the gap
in its statistics and waits for the next parameterized IDR before resuming that
stream; it does not write P frames whose references were lost.

`--list-capabilities` on a connected Ego may enumerate 60 FPS H.264 and H.265
profiles. Enumeration is not an integrity guarantee: the validated `0x1201`,
firmware `0.0.11`, produced decoder errors in dual encoded 60 FPS runs despite
zero frame-index gaps. The CLI therefore **rejects** encoded H.264/H.265 above
30 FPS before opening a device; it never silently writes a 30 FPS file for a
60 FPS request. Use the 1600×1300@30 profiles shown above until a particular
device/firmware/SDK combination has passed both a no-gap capture and a complete
`ffmpeg -v error` decode certification.

Video arrives from OrbbecSDK through a bounded callback queue rather than the
SDK pull queue. The periodic statistics must remain at `0 sequence gaps` and
`video_frame_sets_dropped=0` for a no-loss run. `queue_peak`/`dropped` describe
the separate IMU/audio/metadata publication queue. Treat any nonzero video or
metadata drop count as an acceptance failure and preserve the log for diagnosis.
The plugin stops with a nonzero status if either capture queue fills; it does
not continue with a silently incomplete recording. In SchemaPusher mode, a
single publisher thread owns pushes and warns at 85% queue capacity. Device
state records expose `capture_health`, `failure_reason`, queue capacity/peak,
and dropped-event count so downstream MCAP analysis can reject a run marked
`Incomplete` rather than treating it as valid data.

After either raw-video command, verify that both files are non-empty and fully
decodable. MJPEG needs its input format declared; H.264/H.265 can be inferred
from the filename.

```bash
find "$RUN/raw" -maxdepth 1 -type f -printf '%f %s bytes\n'

# For MJPEG recordings:
ffmpeg -v error -f mjpeg -i "$RUN/raw/left.mjpg" -f null -
ffmpeg -v error -f mjpeg -i "$RUN/raw/right.mjpg" -f null -

# For H.264 recordings:
ffprobe -v error -select_streams v:0 -count_frames -show_streams "$RUN/raw/left.h264"
ffmpeg -v error -i "$RUN/raw/left.h264" -f null -
ffmpeg -v error -i "$RUN/raw/right.h264" -f null -

# For H.265 recordings, substitute the actual run directory:
ffmpeg -v error -i "$RUN/raw/left.h265" -f null -
ffmpeg -v error -i "$RUN/raw/right.h265" -f null -
```

No output from each `ffmpeg -v error` command means decoding succeeded. To
watch a recording, use any desktop player after conversion to MP4 as shown in
[Media inspection and conversion](#media-inspection-and-conversion).

### 3. Show a live preview while recording

```bash
RUN="recordings/ego_preview_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.h265",format=h265,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.h265",format=h265,width=1600,height=1300,fps=30 \
  --preview 2>&1 | tee "$RUN/logs/capture.log"
```

Preview is a timestamp-paired latest-frame consumer and does not alter recording
timestamps. It discards stale work and reuses SDL textures, but CPU decode and
SDL upload can still compete at this resolution. It is therefore a convenience
check, not the 100 ms latency-certified path: record without `--preview` for an
integrity run, and use `camera_viz` for the GPU/NVDEC path. Closing its window
requests normal shutdown. Do not run this plugin and the independent
`camera_viz` Orbbec source against the same physical Ego at the same time.

### 4. Add IMU, audio, calibration, and state

```bash
RUN="recordings/ego_sensors_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.mjpg" \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.mjpg" \
  --enable-imu --imu-rate=1000 --accel-full-scale=24 --gyro-full-scale=2000 \
  --audio-output="$RUN/ego.wav" \
  --calibration-output="$RUN/calibration.json" \
  2>&1 | tee "$RUN/logs/capture.log"
```

The currently validated firmware exposes 24 g and 2000 dps at its enumerated
profile. Always use `--list-capabilities` before selecting a different range.
IMU batches contain SI values (`m/s²`, `rad/s`), temperature, and per-sample
local/device timestamps. PCM is stored once in WAV; MCAP stores a WAV byte offset,
sample count, and timestamps rather than duplicating audio bytes.

## Metadata and MCAP modes

`--mcap-filename` and `--collection-prefix` are strictly mutually exclusive.

### A. Plugin-local MCAP

No Python host or TeleopSession is required. The plugin writes metadata itself:

```bash
RUN="recordings/ego_local_mcap_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.h264",format=h264,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.h264",format=h264,width=1600,height=1300,fps=30 \
  --enable-imu --audio-output="$RUN/ego.wav" \
  --calibration-output="$RUN/calibration.json" \
  --mcap-filename="$RUN/local.mcap" \
  2>&1 | tee "$RUN/logs/capture.log"
```

After a clean stop, confirm all requested artefacts exist. The MCAP's size
alone is not a video-quality indicator: validate the elementary streams with
the commands above and use your MCAP analysis/replay tool to inspect its
metadata channels.

```bash
find "$RUN" -maxdepth 2 -type f -printf '%p %s bytes\n' | sort
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bits_per_raw_sample \
  -of default=noprint_wrappers=1 "$RUN/ego.wav"
# The exported field names are color_left/color_right, not left_intrinsics/right_intrinsics.
jq -e '.color_left and .color_right and .left_to_right' "$RUN/calibration.json"
```

Its channels are:

```text
orbbec_metadata/ColorLeft     orbbec_metadata/ColorRight
orbbec_imu/Accel              orbbec_imu/Gyro
orbbec_audio/Audio
orbbec_calibration/Calibration
orbbec_device/DeviceState
```

### C. Run the repository's OAK-equivalent Orbbec recording sample

`examples/oxr/python/test_orbbec_camera.py` is the Orbbec counterpart to
the repository's OAK camera sample. It exercises the PluginManager launch
path, not just the standalone executable. Use `plugin-mcap` first: it needs
no CloudXR runtime and records both media and every Orbbec metadata class.

The MCAP writer does **not** create a missing parent directory. Create the run
directory before starting the sample; otherwise the plugin exits immediately
with `Unable to open Orbbec MCAP output`.

```bash
cd /absolute/path/to/IsaacTeleop

# Create/update the sample's Python environment once. The local build remains
# first on PYTHONPATH, so this exercises the code built by the CMake commands
# above rather than an unrelated installed isaacteleop wheel.
uv sync --project examples/oxr/python
export PYTHONPATH="$PWD/build/cmake-cpython-311/python_package/Release${PYTHONPATH:+:$PYTHONPATH}"

RUN="recordings/orbbec_plugin_sample_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN"

examples/oxr/python/.venv/bin/python examples/oxr/python/test_orbbec_camera.py \
  --plugin-root "$PWD/build/cmake-cpython-311/src/plugins" \
  --mode plugin-mcap --format mjpg --duration 15 \
  --mcap "$PWD/$RUN/orbbec_plugin.mcap"
```

On a clean 15-second Ego run, the plugin prints nonzero ColorLeft/ColorRight,
Accel, Gyro, and audio sample counts, plus `0 sequence gaps`, `dropped=0`, and
`video_frame_sets_dropped=0`. Confirm that the MCAP is nonempty and that it
contains all seven channels listed above. The sample currently gives raw-media
arguments relative paths, so PluginManager writes its `.mjpg`, `.wav`, and
`calibration.json` under the build-tree plugin working directory:

```bash
PLUGIN_RECORDINGS="$PWD/build/cmake-cpython-311/src/plugins/orbbec_camera/recordings"
find "$RUN" "$PLUGIN_RECORDINGS" -maxdepth 1 -type f -printf '%p %s bytes\n' | sort
ffmpeg -v error -f mjpeg -i "$PLUGIN_RECORDINGS/left.mjpg" -f null -
ffmpeg -v error -f mjpeg -i "$PLUGIN_RECORDINGS/right.mjpg" -f null -
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 "$PLUGIN_RECORDINGS/audio.wav"
```

No output from the two `ffmpeg -v error` commands means both elementary MJPEG
files decoded successfully. The expected WAV report is `pcm_s16le`, `48000`,
and `1`. The sample deliberately leaves its outputs in ignored `recordings/`
directories; do not add these media or MCAP files to Git.

### B. TeleopSession: one MCAP for camera, hands, head, and controllers

This is the multi-device mode. The plugin publishes structured tensors through
OpenXR; the host-side Trackers read them. Add the five Orbbec Trackers **and your
existing hand/head/controller Trackers** to the same `TeleopSessionConfig.trackers`
and the same `McapRecordingConfig`.

The Orbbec plugin must use `--collection-prefix`, not `--mcap-filename`:

```python
from pathlib import Path

from isaacteleop import deviceio
from isaacteleop.teleop_session_manager import PluginConfig, TeleopSession, TeleopSessionConfig

prefix = "orbbec_ego"
run_dir = Path("recordings/ego_teleop_YYYYMMDD_HHMMSS")
(run_dir / "raw").mkdir(parents=True, exist_ok=False)
camera_trackers = [
    deviceio.FrameMetadataTrackerOrbbec(prefix, [
        deviceio.OrbbecCameraStream.ColorLeft,
        deviceio.OrbbecCameraStream.ColorRight,
    ]),
    deviceio.OrbbecImuTracker(prefix),
    deviceio.OrbbecAudioTracker(prefix),
    deviceio.OrbbecCalibrationTracker(prefix),
    deviceio.OrbbecDeviceStateTracker(prefix),
]

# Keep the hand_tracker, head_tracker, and controller_tracker from your existing
# TeleopSession configuration. Their definitions depend on the selected hardware.
all_trackers = [hand_tracker, head_tracker, controller_tracker, *camera_trackers]
recording = deviceio.McapRecordingConfig(
    str(run_dir / "teleop.mcap"),
    [
        (hand_tracker, "hands"),
        (head_tracker, "head"),
        (controller_tracker, "controllers"),
        (camera_trackers[0], "orbbec_metadata"),
        (camera_trackers[1], "orbbec_imu"),
        (camera_trackers[2], "orbbec_audio"),
        (camera_trackers[3], "orbbec_calibration"),
        (camera_trackers[4], "orbbec_device"),
    ],
)

config = TeleopSessionConfig(
    app_name="TeleopWithOrbbec",
    pipeline=pipeline,  # Your existing retargeting pipeline.
    trackers=all_trackers,
    mcap_config=recording,
    plugins=[
        PluginConfig(
            plugin_name="orbbec_camera",
            plugin_root_id="orbbec_camera",
            search_paths=[Path("build/cmake-cpython-311/src/plugins")],
            plugin_args=[
                f"--add-stream=camera=ColorLeft,output={run_dir / 'raw/left.h264'},format=h264,width=1600,height=1300,fps=30",
                f"--add-stream=camera=ColorRight,output={run_dir / 'raw/right.h264'},format=h264,width=1600,height=1300,fps=30",
                "--enable-imu",
                f"--audio-output={run_dir / 'ego.wav'}",
                f"--collection-prefix={prefix}",
            ],
        ),
    ],
)

with TeleopSession(config) as session:
    while recording_is_required:
        session.step()
```

`examples/oxr/python/test_orbbec_camera.py --mode schema-pusher` is the
standalone, hardware-focused example for all five camera Trackers. It does not
create hand/head/controller Trackers, so use the configuration above to combine
them with an existing teleop session.

For a directly runnable camera-only SchemaPusher + `DeviceIOSession` check,
create the output directory before starting the plugin. It verifies the
SchemaPusher transport and all five Orbbec Trackers; `--mcap` controls the one
MCAP written by `DeviceIOSession`. It is not, by itself, a real multi-device
`TeleopSession` with hand/head/controller hardware.

SchemaPusher is an OpenXR path, so its runtime must actually be running before
the script starts. An existing `~/.cloudxr/run/cloudxr.env` file alone is not
enough: it can remain after its runtime has stopped. The commands below use the
examples virtual environment by its full path. This is intentional: on Ubuntu,
`python` is often absent, and a bare `uv pip install` can install dependencies
into a different environment from the one that runs `isaacteleop`.

Terminal A starts the runtime and must remain open for the entire recording:

```bash
cd /absolute/path/to/IsaacTeleop
export TELEOP_PY="$PWD/examples/oxr/python/.venv/bin/python"
test -x "$TELEOP_PY" || { echo "Run: uv sync --project examples/oxr/python"; exit 1; }
export PYTHONPATH="$PWD/build/cmake-cpython-311/python_package/Release${PYTHONPATH:+:$PYTHONPATH}"

# Install both runtime and MCAP-inspection dependencies into this exact venv.
uv pip install --python "$TELEOP_PY" 'websockets>=14' mcap

"$TELEOP_PY" -m isaacteleop.cloudxr \
  --cloudxr-install-dir "$HOME/.cloudxr" \
  --accept-eula
```

```bash
# Terminal B: only after terminal A prints "CloudXR runtime: running".
cd /absolute/path/to/IsaacTeleop
export TELEOP_PY="$PWD/examples/oxr/python/.venv/bin/python"
export PYTHONPATH="$PWD/build/cmake-cpython-311/python_package/Release${PYTHONPATH:+:$PYTHONPATH}"
test -f "$HOME/.cloudxr/run/cloudxr.env" || {
  echo "CloudXR runtime has not written cloudxr.env"; exit 1;
}
source "$HOME/.cloudxr/run/cloudxr.env"
: "${XR_RUNTIME_JSON:?cloudxr.env did not set XR_RUNTIME_JSON}"

RUN="recordings/ego_schema_pusher_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN"
"$TELEOP_PY" examples/oxr/python/test_orbbec_camera.py \
  --plugin-root "$PWD/build/cmake-cpython-311/src/plugins" \
  --mode schema-pusher --format h264 --duration 30 \
  --mcap "$PWD/$RUN/teleop.mcap"

test -s "$RUN/teleop.mcap" || { echo "MCAP is missing or empty"; exit 1; }

# Standard-reader acceptance: every Orbbec channel must be readable.
"$TELEOP_PY" - "$RUN/teleop.mcap" <<'PY'
from collections import Counter
from pathlib import Path
import sys

from mcap.reader import make_reader

expected = {
    "orbbec_metadata/ColorLeft", "orbbec_metadata/ColorRight",
    "orbbec_imu/Accel", "orbbec_imu/Gyro", "orbbec_audio/Audio",
    "orbbec_calibration/Calibration", "orbbec_device/DeviceState",
}
with Path(sys.argv[1]).open("rb") as file:
    counts = Counter(channel.topic for _, channel, _ in make_reader(file).iter_messages())
missing = expected - counts.keys()
if missing:
    raise SystemExit(f"Missing Orbbec MCAP topics: {sorted(missing)}")
for topic in sorted(counts):
    print(f"{topic}: {counts[topic]}")
PY
```

The runtime terminal must remain open until the test exits. The resulting MCAP
is written by `DeviceIOSession`, together with any hand/head/controller Tracker
channels added to a real `TeleopSession`; raw video and WAV remain separate
media files as designed. For this standalone example, PluginManager launches
the plugin from its build-tree working directory, so they are under
`build/cmake-cpython-311/src/plugins/orbbec_camera/recordings/` rather than
`$RUN`. A real TeleopSession configuration should pass one dedicated run
directory in every `plugin_args` output path, as in the Python template.

## Device controls

All control values are validated against the connected SDK's permissions, type,
range, and integer step. Original values are restored on normal exit unless
`--persist-controls` is supplied.

| Goal | Option |
|---|---|
| Manual exposure | `--exposure=N` |
| Gain | `--gain=N` |
| Manual white balance | `--white-balance=N` |
| Brightness / sharpness / saturation / contrast | `--brightness=N`, `--sharpness=N`, `--saturation=N`, `--contrast=N` |
| Anti-flicker | `--power-frequency=N` |
| Auto exposure or any other SDK property | `--set-property=OB_PROP_COLOR_AUTO_EXPOSURE_BOOL=0` or `=1` |
| Bitrate / adaptive bitrate | `--bitrate=N`, `--dynamic-bitrate=on|off` |
| Keep settings after exit | `--persist-controls` |

Ego has no OAK-equivalent `--quality` property. Use bitrate and dynamic bitrate;
the plugin intentionally rejects a misleading `--quality` option.

For every non-persistent control run, require one `Restored PROPERTY=VALUE`
line for every `Set PROPERTY=VALUE` line and no `Failed to restore` line before
accepting the recording. `timeout` returns status 124 when it delivers its
planned SIGINT; that is acceptable only when the plugin prints all restore
lines and neither crashes nor reports a restore failure.

Some firmware can report a self-contradictory integer range (the tested Ego's
brightness reports `0..3` with step `7`). The plugin refuses to change such a
property because its original value cannot be restored safely. This is a
firmware capability-reporting limitation, not permission to use
`--persist-controls`; use only controls whose enumerated range and step are
consistent.

### Non-persistent control acceptance

Run this on a physical camera only. It deliberately omits `--persist-controls`.
First save the exact capabilities, then select values from that file; the
numbers below were accepted by the tested Ego but are not portable defaults for
another model or firmware.

```bash
cd /absolute/path/to/IsaacTeleop
export ORBBEC_PLUGIN="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec"
export RUN="recordings/acceptance/controls_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw" "$RUN/logs"

"$ORBBEC_PLUGIN" --list-capabilities | tee "$RUN/capabilities_before.txt"

# Replace values only with values allowed by capabilities_before.txt.
# Do not include --brightness when its SDK range/step is inconsistent.
timeout --foreground -s INT -k 15s 10s "$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/left.h264",format=h264,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output="$RUN/raw/right.h264",format=h264,width=1600,height=1300,fps=30 \
  --set-property=OB_PROP_COLOR_AUTO_EXPOSURE_BOOL=0 \
  --set-property=OB_PROP_COLOR_AUTO_WHITE_BALANCE_BOOL=0 \
  --exposure=1000 --gain=100 --white-balance=5000 \
  --sharpness=20 --saturation=128 --contrast=50 --power-frequency=1 \
  2>&1 | tee "$RUN/logs/controls.log"

"$ORBBEC_PLUGIN" --list-capabilities | tee "$RUN/capabilities_after.txt"
rg '^(Set|Restored|Failed to restore)' "$RUN/logs/controls.log"
ffmpeg -v error -i "$RUN/raw/left.h264" -f null -
ffmpeg -v error -i "$RUN/raw/right.h264" -f null -
```

For this run, every `Set` line must have exactly one matching `Restored` line,
there must be no `Failed to restore`, no `terminate called`, and both FFmpeg
commands must exit successfully. The `timeout` status may be 124 after its
planned SIGINT; use the plugin's restore lines and absence of a crash as the
clean-stop criterion. `--quality=80` must fail as an unknown option. A
firmware-reported invalid brightness range must fail before capture and leave
the property unchanged; that safe refusal is the expected result.

Device state publishes readable property snapshots and the SDK temperature snapshot
every five seconds, in addition to Ego state-callback changes. Calibration exports
structured stereo intrinsics and left-to-right extrinsics (and camera-to-IMU
extrinsics when the active SDK profile supplies them), plus the original alignment
and IMU YAML. Some Ego firmware indexes SDK calibration by MJPEG profile even for
encoded streams; the plugin reports that condition and falls back to the raw
alignment YAML rather than discarding usable stereo calibration.

## Configuration reference

| Option | Default | Meaning |
|---|---|---|
| `--add-stream=camera=...,output=...[,format=...,width=...,height=...,fps=...]` | required | `camera` is `ColorLeft` or `ColorRight`; repeat once per active sensor. |
| `--width`, `--height`, `--fps` | `0` | Global defaults; zero selects SDK-compatible defaults. Stream values win. |
| `--device-uid=UID` | first device with requested ColorLeft/ColorRight capabilities | Select one device; PID is never used as a rejection rule. |
| `--bitrate=N` | SDK setting unchanged | Device H.264/H.265 bitrate property. |
| `--dynamic-bitrate=on|off` | unchanged | Device dynamic-bitrate property. |
| `--preview` | off | Timestamp-paired, latest-frame side-by-side SDL preview. CPU decode only; use camera_viz for NVDEC. |
| `--enable-imu` | off | Enable both accelerometer and gyro. |
| `--imu-rate=400|1000` | `400` | Requested IMU ODR. |
| `--accel-full-scale`, `--gyro-full-scale` | 24 g / 2000 dps | Requested IMU range; must match the device profile. |
| `--audio-output=PATH.wav` | off | Enable PCM WAV recording. |
| `--calibration-output=PATH.json` | off | Export calibration JSON/YAML. |
| `--mcap-filename=PATH` | off | Plugin-local metadata MCAP. |
| `--collection-prefix=PREFIX` | off | OpenXR/TeleopSession metadata mode. |
| `--list-capabilities` | off | Print sensors, profiles, and properties then exit. |

## Media inspection and conversion

Elementary video has no container index, so many desktop players will not open
it directly. First validate it with `ffmpeg`, then remux/convert it to MP4.
Run the command that matches the format actually recorded; it writes an MP4
beside the raw file. Replace `left` with `right` to view the other eye.

```bash
# Inspect raw streams and WAV.
ffprobe -v error -show_streams "$RUN/raw/left.h264"
ffprobe -v error -show_streams "$RUN/ego.wav"

# Copy supported elementary codecs into MP4 without re-encoding.
ffmpeg -f h264 -framerate 30 -i "$RUN/raw/left.h264" -c:v copy "$RUN/left.mp4"
ffmpeg -f hevc -framerate 30 -i "$RUN/raw/left.h265" -c:v copy "$RUN/left.mp4"

# MJPEG normally needs video re-encoding for MP4.
ffmpeg -f mjpeg -framerate 30 -i "$RUN/raw/left.mjpg" -c:v libx264 -pix_fmt yuv420p "$RUN/left.mp4"

# Open the generated MP4 and WAV with the desktop's default player.
xdg-open "$RUN/left.mp4"
xdg-open "$RUN/ego.wav"
```

Use a video frame's `sample_time_local_common_clock_ns` / device timestamp and an
audio chunk's WAV offset/sample count to align elementary media with MCAP records.
MCAP is not a video container and will not play the camera image: it is the
structured timing/metadata companion to the media files. Inspect it in the
MCAP-capable analysis application used by your team, or replay it through an
Isaac `ReplaySession` configured with the same Orbbec Tracker-to-channel mapping
as the original recording. In local mode there are five channel bases
(`orbbec_metadata`, `orbbec_imu`, `orbbec_audio`, `orbbec_calibration`, and
`orbbec_device`); in TeleopSession mode they are the names supplied in
`McapRecordingConfig` (for example `orbbec_metadata` and `orbbec_imu`).

### MCAP replay acceptance

MCAP replay validates structured Tracker data; it does not play the camera
video. Use a completed local-mode recording, the examples virtual environment,
and the current build-tree Python package. Do not substitute `uv run python`:
it can resolve an older installed wheel that lacks the Orbbec Trackers.

```bash
cd /absolute/path/to/IsaacTeleop
export RUN="/absolute/path/to/the/local-mcap-run-directory"
export TELEOP_PY="$PWD/examples/oxr/python/.venv/bin/python"
export PYTHONPATH="$PWD/build/cmake-cpython-311/python_package/Release${PYTHONPATH:+:$PYTHONPATH}"

test -s "$RUN/local.mcap" || { echo "local.mcap is missing or empty"; exit 1; }

"$TELEOP_PY" - "$RUN/local.mcap" <<'PY'
import sys

from isaacteleop import deviceio

prefix = "orbbec_ego"
frame = deviceio.FrameMetadataTrackerOrbbec(
    prefix,
    [deviceio.OrbbecCameraStream.ColorLeft, deviceio.OrbbecCameraStream.ColorRight],
)
imu = deviceio.OrbbecImuTracker(prefix)
audio = deviceio.OrbbecAudioTracker(prefix)
calibration = deviceio.OrbbecCalibrationTracker(prefix)
state = deviceio.OrbbecDeviceStateTracker(prefix)
config = deviceio.McapReplayConfig(
    sys.argv[1],
    [
        (frame, "orbbec_metadata"), (imu, "orbbec_imu"),
        (audio, "orbbec_audio"), (calibration, "orbbec_calibration"),
        (state, "orbbec_device"),
    ],
)

expected = {"ColorLeft", "ColorRight", "Accel", "Gyro", "Audio", "Calibration", "DeviceState"}
seen = set()
with deviceio.ReplaySession.run(config) as replay:
    for update in range(1500):
        replay.update()
        values = {
            "ColorLeft": frame.get_stream_data(replay, 0).data,
            "ColorRight": frame.get_stream_data(replay, 1).data,
            "Accel": imu.get_stream_data(replay, 0).data,
            "Gyro": imu.get_stream_data(replay, 1).data,
            "Audio": audio.get_data(replay).data,
            "Calibration": calibration.get_data(replay).data,
            "DeviceState": state.get_data(replay).data,
        }
        seen.update(name for name, value in values.items() if value is not None)
        if seen == expected:
            print(f"All Orbbec classes materialized by replay update {update + 1}")
            break

missing = expected - seen
if missing:
    raise SystemExit(f"Replay never materialized: {sorted(missing)}")
print("Orbbec MCAP replay acceptance passed")
PY
```

Passing output contains both `All Orbbec classes materialized` and `Orbbec
MCAP replay acceptance passed`. The replay requires no camera, CloudXR runtime,
or XR headset.

## Reproducible build and delivery checks

Before shipping a change, validate the same source revision in an empty Ubuntu
22.04 Docker container and validate the camera on a physical host with the Ego
connected directly.
Docker is only for the build/install check: udev, direct USB capture, SDL, CUDA,
and XR are host-side checks. Install Docker Engine from Docker's official Ubuntu
instructions, then use the checked-in
`src/plugins/orbbec/cleanroom/Dockerfile`:

```bash
git archive --format=tar HEAD | sudo docker build --pull --no-cache \
  --build-context orbbec_sdk=/absolute/path/to/OrbbecSDK_v2 \
  -f src/plugins/orbbec/cleanroom/Dockerfile \
  -t isaacteleop-orbbec-cleanroom -
```

The successful image contains `/opt/isaacteleop-install`; it runs every CTest
available without proprietary CloudXR runtime files and verifies that the
installed plugin resolves its SDK from its own directory. The single excluded
test, `cloudxr_test_launcher`, requires NVIDIA's separately licensed
`libcloudxr.so`; CloudXR CI covers it after obtaining that SDK. `--no-cache` is
intentional: it prevents an earlier successful build from hiding a missing
package.

1. Start from a clean Git revision (including all new Orbbec files) and export it
   with `git archive`; do not mount an old build tree, `install/`, `Log/`, or a
   developer's `uv` cache into the container. The command above does this.
2. The Dockerfile installs the packages listed above plus `git`, `curl`, and
   `ca-certificates`, then configures with:

   ```bash
   cmake --preset py3.11 -DBUILD_VIZ=OFF \
     -DBUILD_PLUGIN_ORBBEC_CAMERA=ON \
     -DORBBEC_SDK_ROOT=/opt/orbbec-sdk
   cmake --build build/cmake-cpython-311 --parallel
   ctest --test-dir build/cmake-cpython-311 --output-on-failure -j "$(nproc)" \
     -E '^cloudxr_test_launcher$'
   cmake --install build/cmake-cpython-311 --prefix /opt/isaacteleop-install
   ```

   If the host shell has sourced ROS, clear its Python overlays before running
   CTest. ROS Humble's Python 3.10 packages otherwise contaminate the managed
   Python 3.11 test environment:

   ```bash
   env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
     UV_CACHE_DIR=/tmp/isaacteleop-uv-cache \
     ctest --test-dir build/cmake-cpython-311 --output-on-failure -j "$(nproc)" \
       -E '^cloudxr_test_launcher$'
   ```

3. Run `ldd /opt/isaacteleop-install/plugins/orbbec_camera/camera_plugin_orbbec`.
   It must contain no `not found` entries and must resolve `libOrbbecSDK.so.2`
   from the plugin directory, not from the external SDK directory.
4. On the physical host, first record the outputs of `lsusb -t`, `nvidia-smi`,
   and `--list-capabilities`. Ego PID `0x1201` normally reports `bcdUSB 2.00`
   and `480M`; that is its expected transport, not a failed acceptance check.
5. For the 15-minute load check use two H.264 or H.265 1600x1300@30 streams,
   `--enable-imu --imu-rate=1000`, audio, and local MCAP. Monitor the process
   with `pidstat -r -u -d -p <pid> 10` and preserve the plugin's periodic
   frame/sample/queue statistics. `dropped_events` must remain zero, the queue
   peak must remain below 4096, timestamps must not go backward, and memory must
   plateau after warm-up rather than grow continuously.

### Physical-camera acceptance checklist

Run these checks on the physical host with the camera directly connected. They
are intentionally separate from the Docker build because a container cannot
establish camera bandwidth, device permissions, display, CUDA, or XR behavior.

```bash
# 1. Record the transport and save the firmware's profiles/property ranges.
#    For Ego PID 0x1201, bcdUSB 2.00 and 480M are expected.
lsusb -t
lsusb -v -d 2bc5:1201 2>/dev/null | grep -E 'bcdUSB|iProduct|MaxPower'
"$ORBBEC_PLUGIN" --list-capabilities | tee recordings/capabilities.txt

# 2. Exercise every encoded video format independently. Substitute only a
#    profile reported by the previous command.
for format in mjpg h264 h265; do
  status=0
  timeout -s INT 20 "$ORBBEC_PLUGIN" \
    --add-stream=camera=ColorLeft,output="recordings/left.${format}",format="$format",width=1600,height=1300,fps=30 \
    --add-stream=camera=ColorRight,output="recordings/right.${format}",format="$format",width=1600,height=1300,fps=30 \
    || status=$?
  # GNU timeout returns 124 after deliberately sending SIGINT at 20 seconds.
  # Treat that expected stop as success, including in shells using `set -e`.
  if [[ "$status" -ne 0 && "$status" -ne 124 ]]; then
    exit "$status"
  fi
done

# 3. Verify codec, size, rate, and decoded frame count. H.264/HEVC must decode
#    with no ffmpeg errors on the physical acceptance host.
ffprobe -v error -select_streams v:0 -count_frames -show_streams recordings/left.h264
ffmpeg -v error -i recordings/left.h264 -f null -
ffprobe -v error -select_streams v:0 -count_frames -show_streams recordings/left.h265
ffmpeg -v error -i recordings/left.h265 -f null -

# 4. Record structured data and local MCAP together; stop with Ctrl-C after a
#    representative interval, then check the resulting WAV.
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output=recordings/left.mjpg \
  --add-stream=camera=ColorRight,output=recordings/right.mjpg \
  --enable-imu --imu-rate=1000 --accel-full-scale=24 --gyro-full-scale=2000 \
  --audio-output=recordings/ego.wav \
  --calibration-output=recordings/ego_calibration.json \
  --mcap-filename=recordings/local.mcap
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bits_per_raw_sample \
  -of default=noprint_wrappers=1 recordings/ego.wav
jq -e '.color_left and .color_right and .left_to_right' recordings/ego_calibration.json
```

Do not use an unguarded ``timeout`` loop in a shell that enables ``set -e``:
its expected status ``124`` otherwise stops after the first format.

For the MCAP, verify the five expected schema families and the channel names in
the plugin-local list above with the MCAP reader used by your analysis workflow.
Verify that IMU batch timestamps are monotonic, their sample count is consistent
with the elapsed time at 400/1000 Hz, and each audio record's WAV byte range is
within `ego.wav`. Repeat step 4 through the SchemaPusher example and confirm its
records appear beside the hand, head, and controller records in **one**
TeleopSession MCAP. Also confirm that supplying both `--mcap-filename` and
`--collection-prefix` fails before capture begins.

The following is the supported 15-minute stress command. The pass/fail criterion
is sustained capture quality and the recorded statistics, not a SuperSpeed USB
enumeration. Do **not** change it to 60 FPS merely because the profile is
enumerated: as documented above, encoded 60 FPS has not passed integrity
validation on the validated Ego firmware.

```bash
mkdir -p recordings/stress
"$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output=recordings/stress/left.h265,format=h265,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output=recordings/stress/right.h265,format=h265,width=1600,height=1300,fps=30 \
  --enable-imu --imu-rate=1000 --accel-full-scale=24 --gyro-full-scale=2000 \
  --audio-output=recordings/stress/ego.wav \
  --mcap-filename=recordings/stress/local.mcap
```

In a second terminal, obtain the plugin PID with `pgrep -f camera_plugin_orbbec`
and run `pidstat -r -u -d -p <PID> 10`. Keep the capture running for 10--15
minutes, then decode both streams, inspect the WAV/MCAP, and retain the log.
An H.265 "Could not find ref" message, rising memory, timestamp regression,
nonzero dropped-event count, or persistent sequence gaps is a failed acceptance
result; first rule out USB topology before changing software.

## camera_viz GPU stereo

`camera_viz` is a separate visual path, not a TeleopSession Tracker. It returns
paired CuPy GPU RGBA8 images as `Frame.image` (left) and `Frame.image_right`
(right). H.264/H.265 use NVDEC; MJPEG is SDK-decoded then uploaded from pinned host
memory.

```bash
examples/camera_viz/camera_viz.sh setup \
  --with-orbbec --orbbec-sdk-root /absolute/path/to/OrbbecSDK_v2.9.0_linux_x86_64
examples/camera_viz/camera_viz.sh run examples/camera_viz/configs/orbbec_ego.yaml --mode window
```

The default config is H.264 1600x1300@30. Change its `format` to `h265` or `mjpg`
and choose only profiles shown by `--list-capabilities`.

## Troubleshooting

| Symptom | Check |
|---|---|
| No device / permission error | Install the matching SDK udev rules; reconnect; run `--list-capabilities`. |
| Profile not found | Use the exact format, size, FPS, IMU ODR, and range printed by `--list-capabilities`. |
| Dropped stereo frames | Avoid hubs and simultaneous high-bandwidth USB devices; select a profile reported by `--list-capabilities`, then reduce FPS/resolution if needed. |
| Preview cannot start | Confirm an active display plus SDL2 and FFmpeg development/runtime libraries. |
| H.264/H.265 cannot decode | Stop cleanly, inspect with `ffprobe`, and verify the requested stream profile exists. |
| `--mcap-filename` and `--collection-prefix` fail together | Choose plugin-local MCAP or TeleopSession MCAP; they are intentionally exclusive. |
| No data in TeleopSession | The Tracker prefix and plugin `--collection-prefix` must be identical; call `session.step()` continuously. |
| Docker CMake configuration fails while cloning a public GitHub dependency with `gnutls_handshake()` | This is a Docker-network interruption, not an Orbbec build error. The Dockerfile forces Git to HTTP/1.1; rebuild from the amended `HEAD`. If it persists, check Docker daemon proxy/DNS access to `github.com` and retry. |
