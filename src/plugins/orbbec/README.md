<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Orbbec Ego Camera Plugin

This plugin connects capability-compatible Orbbec Ego stereo cameras to Isaac
Teleop. It captures `ColorLeft` and `ColorRight` video and, when the connected
device exposes them, accelerometer, gyroscope, microphone, calibration, and
device state.

The validated reference device is Ego PID `0x1201`; PID is reported, not used
as the sole compatibility check. The plugin selects a device from its actual
left/right color sensors and advertised profiles. Ego has no Depth or IR
sensors, so depth, IR, D2C, and point-cloud features are intentionally out of
scope.

## What you can do

- Record stereo MJPEG, H.264, or H.265 elementary streams without a container.
- Record 48 kHz, mono, S16_LE PCM audio as WAV.
- Record frame metadata, IMU batches, audio offsets, calibration, and device
  state in MCAP.
- Choose raw-media-only, plugin-local MCAP, or TeleopSession MCAP workflows.
- Create a self-contained private `embedded` MCAP containing encoded video and
  PCM audio, then export it back to video files and WAV.
- Inspect device capabilities and apply validated exposure, gain, white-balance,
  image, bitrate, and IMU controls.
- Preview stereo video with the plugin's SDL window or use the independent
  GPU `camera_viz` source.

H.264/H.265 above 30 FPS are deliberately rejected. The device may enumerate
60 FPS profiles, but they are not yet certified for raw bitstream integrity.

## Prerequisites

Use Ubuntu 22.04 x86_64 and an extracted Linux x86_64 OrbbecSDK package. The
SDK is an external dependency and is not distributed by this repository. Its
root directory must contain:

```text
include/libobsensor/ObSensor.hpp
lib/OrbbecSDKConfig.cmake
lib/libOrbbecSDK.so.2
lib/extensions/
```

The standard host tools are CMake, a C++ compiler, Python, `uv`, FFmpeg, and
the Isaac Teleop preset dependencies. For the plugin preview also install SDL2
and FFmpeg development packages:

```bash
sudo apt update
sudo apt install -y build-essential cmake ccache clang-format-14 patchelf \
  pkg-config libudev-dev libsdl2-dev libavcodec-dev libavutil-dev libswscale-dev \
  ffmpeg jq usbutils
```

Install the udev rules provided by the **same SDK release** before using the
camera as a non-root user. For the tested SDK package this is normally:

```bash
sudo /path/to/OrbbecSDK/shared/install_udev_rules.sh
```

Reconnect the camera after installing rules. A desktop session is required for
`--preview`. The reference Ego reports `bcdUSB 2.00` / `480M` in `lsusb -t`,
which is normal for this device even on a USB 3.x host port.

## Quick start: build, record, verify

The recommended entry point is `orbbec_ego.sh`. It never installs packages,
downloads SDKs, or runs `sudo`; `doctor` reports missing requirements and shows
the appropriate command instead.

Open a fresh terminal at the repository root:

```bash
cd /absolute/path/to/IsaacTeleop
export ORBBEC_SDK=/absolute/path/to/OrbbecSDK_v2_linux_x86_64

# 1. Inspect host dependencies, SDK layout, USB access, and preview libraries.
./src/plugins/orbbec/orbbec_ego.sh doctor --sdk-root "$ORBBEC_SDK"

# 2. Configure and build only the Orbbec plugin and embedded-media exporter.
./src/plugins/orbbec/orbbec_ego.sh build --sdk-root "$ORBBEC_SDK" --jobs 8

# 3. Inspect the connected camera's actual profiles and control ranges.
./src/plugins/orbbec/orbbec_ego.sh capabilities

# 4. Record the supported default: stereo H.264 1600x1300@30, plus available
#    IMU/audio, calibration, and a local metadata MCAP.
./src/plugins/orbbec/orbbec_ego.sh record --duration 30
```

The final command creates a Git-ignored directory:

```text
recordings/orbbec_ego_<timestamp>/
├── raw/ColorLeft.h264
├── raw/ColorRight.h264
├── Audio.wav
├── calibration.json
├── metadata.mcap
├── capabilities.txt
└── logs/capture.log
```

For an unlimited recording, omit `--duration` and stop with `Ctrl-C`. Wait for
the final statistics and the shell prompt; this finalizes WAV and MCAP output.

Verify the run before sharing it. Do not type angle-bracket placeholders such
as `<timestamp>` literally: replace them with the real directory name.

```bash
python3 -m pip install --user mcap  # only if verify asks for it

RUN="$(ls -dt recordings/orbbec_ego_*/ | head -n 1)"
./src/plugins/orbbec/orbbec_ego.sh verify "$RUN"
```

Success prints `Verification passed`, the delivery MCAP path, both H.264
streams decode with FFmpeg, the WAV is 48 kHz/mono/S16_LE, and the MCAP has a
Footer and its required topics.

### One-command script reference

```bash
./src/plugins/orbbec/orbbec_ego.sh doctor --sdk-root "$ORBBEC_SDK"
./src/plugins/orbbec/orbbec_ego.sh build --sdk-root "$ORBBEC_SDK" [--jobs N] [--clean]
./src/plugins/orbbec/orbbec_ego.sh capabilities
./src/plugins/orbbec/orbbec_ego.sh record [options] [-- PLUGIN_OPTIONS...]
./src/plugins/orbbec/orbbec_ego.sh verify RUN_DIRECTORY
```

Useful recording options:

```bash
# Select format/profile or output location.
./src/plugins/orbbec/orbbec_ego.sh record --duration 30 \
  --format h265 --width 1600 --height 1300 --fps 30 \
  --output recordings/demo_h265

# Disable optional sensors, choose one camera, or show the SDL preview.
./src/plugins/orbbec/orbbec_ego.sh record --duration 30 \
  --device-uid DEVICE_UID --no-imu --preview

# Pass advanced native controls unchanged after --.
./src/plugins/orbbec/orbbec_ego.sh record --duration 30 -- \
  --bitrate=8 --dynamic-bitrate=on
```

`record` automatically requests IMU and audio only if the device advertises
them. It never silently changes an unsupported requested profile to another
profile.

## Recording modes

There are three recording workflows. `--mcap-filename` and
`--collection-prefix` are mutually exclusive.

| Workflow | Use it when | Media location |
|---|---|---|
| Raw media only | You only need video and/or WAV. | `.mjpg`, `.h264`, `.h265`, `.wav` files. |
| Plugin-local MCAP | You need camera timing and sensor data in one local MCAP. | Default: sidecar video/WAV plus `metadata.mcap`. |
| TeleopSession MCAP | You need camera data alongside hand, head, controller, or other trackers. | DeviceIO writes the shared MCAP; raw media remains sidecar by default. |

### Raw media only

Use the native plugin directly when no MCAP is needed:

```bash
ORBBEC_PLUGIN="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec"
RUN="recordings/raw_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN/raw"

timeout -s INT 30 "$ORBBEC_PLUGIN" \
  --add-stream=camera=ColorLeft,output="$RUN/raw/ColorLeft.h264",format=h264,width=1600,height=1300,fps=30 \
  --add-stream=camera=ColorRight,output="$RUN/raw/ColorRight.h264",format=h264,width=1600,height=1300,fps=30 \
  --audio-output="$RUN/Audio.wav"
```

The command ends normally after 30 seconds. Check `ColorLeft.h264`,
`ColorRight.h264`, and `Audio.wav` are non-empty, then use the media checks in
[Inspect and play recordings](#inspect-and-play-recordings).

### Local metadata MCAP (default script behavior)

The quick-start `record` command uses this mode. It writes the lightweight
structured topics below while leaving high-throughput video and WAV as regular
files:

```text
orbbec_metadata/ColorLeft, orbbec_metadata/ColorRight
orbbec_imu/Accel,           orbbec_imu/Gyro
orbbec_audio/Audio
orbbec_calibration/Calibration
orbbec_device/DeviceState
```

This is the recommended default because it is easy to inspect, avoids copying
media bytes into an MCAP, and keeps video playable through standard tools.

### Self-contained private embedded MCAP

Use `embedded` only when one private Orbbec MCAP must contain video bytes, PCM
audio, metadata, IMU, calibration, and state. It does not transcode the data.
During recording the file has a `.partial` suffix and is renamed only after a
valid MCAP Footer is written.

```bash
RUN="recordings/embedded_$(date +%Y%m%d_%H%M%S)"
./src/plugins/orbbec/orbbec_ego.sh record --duration 30 \
  --output "$RUN" --mcap-media embedded
./src/plugins/orbbec/orbbec_ego.sh verify "$RUN"
```

In this mode no sidecar video/WAV is written unless you add
`--keep-media-sidecars`. The private media channels are:

```text
orbbec_media/ColorLeft
orbbec_media/ColorRight
orbbec_media/Audio
```

Export a completed embedded MCAP for ordinary playback:

```bash
EXPORTER="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/orbbec_mcap_export_media"
"$EXPORTER" "$RUN/metadata.mcap" "$RUN/exported"
```

The output is `ColorLeft.<format>`, `ColorRight.<format>`, and `Audio.wav`.
A remaining `metadata.mcap.partial` means the capture was interrupted or
failed; do not treat it as a deliverable.

### TeleopSession: one MCAP with other trackers

For multi-device recording, create the five Orbbec Trackers together with your
existing hand/head/controller Trackers, and give them channels in the same
`McapRecordingConfig`:

```python
from isaacteleop import deviceio

prefix = "orbbec_ego"
trackers = [
    deviceio.FrameMetadataTrackerOrbbec(
        prefix,
        [deviceio.OrbbecCameraStream.ColorLeft, deviceio.OrbbecCameraStream.ColorRight],
    ),
    deviceio.OrbbecImuTracker(prefix),
    deviceio.OrbbecAudioTracker(prefix),
    deviceio.OrbbecCalibrationTracker(prefix),
    deviceio.OrbbecDeviceStateTracker(prefix),
]

# Add these trackers to the same TeleopSession and McapRecordingConfig as the
# configured hand, head, and controller trackers.
```

Use plugin arguments such as:

```text
--collection-prefix=orbbec_ego
--add-stream=camera=ColorLeft,output=<run>/raw/ColorLeft.h264,format=h264,width=1600,height=1300,fps=30
--add-stream=camera=ColorRight,output=<run>/raw/ColorRight.h264,format=h264,width=1600,height=1300,fps=30
--enable-imu
--audio-output=<run>/Audio.wav
```

This publishes structured Orbbec data through SchemaPusher; the TeleopSession
MCAP then contains Orbbec channels and any configured hand/head/controller
channels. It requires a running OpenXR runtime. Camera-only testing is covered
by `examples/oxr/python/test_orbbec_camera.py`; a physical XR setup is required
to accept a true multi-device session.

## Inspect and play recordings

Elementary video has no container index. Validate it first, then remux it into
MP4 for a desktop player:

```bash
# Replace RUN with a real recording directory.
ffmpeg -v error -f h264 -i "$RUN/raw/ColorLeft.h264" -f null -
ffmpeg -v error -f h264 -i "$RUN/raw/ColorRight.h264" -f null -
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 "$RUN/Audio.wav"

ffmpeg -f h264 -framerate 30 -i "$RUN/raw/ColorLeft.h264" -c:v copy "$RUN/ColorLeft.mp4"
xdg-open "$RUN/ColorLeft.mp4"
xdg-open "$RUN/Audio.wav"
```

For H.265 replace `h264` with `hevc`; for MJPEG use:

```bash
ffmpeg -f mjpeg -framerate 30 -i "$RUN/raw/ColorLeft.mjpg" \
  -c:v libx264 -pix_fmt yuv420p "$RUN/ColorLeft.mp4"
```

MCAP is structured recording data, not a generic video player. List its topics
with the standard reader:

```bash
python3 - "$RUN/metadata.mcap" <<'PY'
from collections import Counter
from pathlib import Path
import sys
from mcap.reader import make_reader

path = Path(sys.argv[1])
with path.open("rb") as stream:
    counts = Counter(channel.topic for _, channel, _ in make_reader(stream).iter_messages())
for topic in sorted(counts):
    print(f"{topic}: {counts[topic]}")
PY
```

## Device controls

Always inspect the connected device first. Property availability, range, and
step are firmware-specific:

```bash
./src/plugins/orbbec/orbbec_ego.sh capabilities | tee capabilities.txt
```

Use only values reported by that command. The plugin validates permissions,
type, range, and step before capture. It restores changed properties at normal
exit unless `--persist-controls` is explicitly supplied.

```bash
./src/plugins/orbbec/orbbec_ego.sh record --duration 20 -- \
  --set-property=OB_PROP_COLOR_AUTO_EXPOSURE_BOOL=0 \
  --exposure=1000 --gain=100 \
  --set-property=OB_PROP_COLOR_AUTO_WHITE_BALANCE_BOOL=0 \
  --white-balance=5000 --sharpness=20 --saturation=128 --contrast=50 \
  --power-frequency=1
```

Supported friendly options are `--exposure`, `--gain`, `--white-balance`,
`--brightness`, `--sharpness`, `--saturation`, `--contrast`, and
`--power-frequency`. `--set-property=SDK_PROPERTY_NAME=VALUE` is the escape
hatch for other writable SDK properties. Ego has no OAK-equivalent `--quality`;
use `--bitrate` and `--dynamic-bitrate` instead.

Do not use `--persist-controls` for routine testing. It intentionally leaves
the selected values on the physical device.

## Preview and GPU stereo

Add `--preview` to a native plugin command or the one-command script to open a
side-by-side SDL preview while recording:

```bash
./src/plugins/orbbec/orbbec_ego.sh record --duration 30 --preview
```

The preview is a convenience CPU decode path and can drop stale display frames
without changing recording timestamps. It must not be used as an NVDEC latency
acceptance path.

For GPU-resident frames, use the independent `camera_viz` source:

```bash
examples/camera_viz/camera_viz.sh setup \
  --with-orbbec --orbbec-sdk-root "$ORBBEC_SDK"
examples/camera_viz/camera_viz.sh run \
  examples/camera_viz/configs/orbbec_ego.yaml --mode window
```

`camera_viz` and the recording plugin both open the physical camera; do not run
them against the same Ego at the same time. Desktop window mode normally shows
the left eye; use the configuration's side-by-side option for stereo debugging.
XR mode submits separate left/right textures.

## Native CLI reference

The script covers normal work. Use the executable directly only for custom
workflows:

```bash
ORBBEC_PLUGIN="$PWD/build/cmake-cpython-311/src/plugins/orbbec/app/camera_plugin_orbbec"
"$ORBBEC_PLUGIN" --help
"$ORBBEC_PLUGIN" --list-capabilities
```

Important options:

| Option | Meaning |
|---|---|
| `--add-stream=camera=...,output=...[,format=...,width=...,height=...,fps=...]` | Add one ColorLeft or ColorRight stream. Stream values override global values. |
| `--device-uid=UID` | Select one enumerated camera. |
| `--enable-imu --imu-rate=400\|1000` | Capture accelerometer and gyroscope when available. |
| `--audio-output=PATH.wav` | Capture PCM audio as WAV. |
| `--calibration-output=PATH.json` | Export structured calibration and original SDK YAML. |
| `--mcap-filename=PATH` | Write a plugin-local MCAP. |
| `--collection-prefix=PREFIX` | Publish data for a TeleopSession. |
| `--mcap-media=metadata-only\|embedded` | Select sidecar or private self-contained local media handling. |
| `--keep-media-sidecars` | Also write raw video/WAV in embedded mode. |
| `--mcap-media-spool=PATH` | Required for embedded TeleopSession media merging. |

## Build, installation, and review checks

The script uses the equivalent CMake commands below. Use them when integrating
the plugin into an existing build or CI job:

```bash
cmake --preset py3.11 -DBUILD_VIZ=OFF \
  -DBUILD_PLUGIN_ORBBEC_CAMERA=ON \
  -DORBBEC_SDK_ROOT="$ORBBEC_SDK"
cmake --build build/cmake-cpython-311 \
  --target camera_plugin_orbbec orbbec_mcap_export_media --parallel
```

After installation, `orbbec_ego.sh` is installed beside the Orbbec plugin and
supports `capabilities`, `record`, and `verify`. Its `build` command is only
for a source checkout.

For a reproducible build, use the checked-in clean-room Dockerfile. Docker
validates source + separately supplied SDK; camera access, udev, SDL, CUDA, and
XR remain host-side tests.

```bash
git archive --format=tar HEAD | sudo docker build --pull --no-cache \
  --build-context orbbec_sdk="$ORBBEC_SDK" \
  -f src/plugins/orbbec/cleanroom/Dockerfile \
  -t isaacteleop-orbbec-cleanroom -
```

Before a review or release:

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH \
  UV_CACHE_DIR=/tmp/isaacteleop-uv-cache \
  ctest --test-dir build/cmake-cpython-311 --output-on-failure -R orbbec

SKIP=check-copyright-year pre-commit run --all-files
git diff --check
```

Do not commit `recordings/`, `build/`, SDK extracts, `Log/`, or IDE files. The
repository packages neither the OrbbecSDK nor its license; a product release
must separately verify SDK redistribution rights, supported firmware, and udev
installation.

## Troubleshooting

| Symptom | Check |
|---|---|
| `doctor` reports no camera or no USB access | Install the selected SDK's udev rules, reconnect the camera, then run `doctor` and `capabilities` again. |
| Requested profile fails | Run `capabilities`; use only an advertised profile. H.264/H.265 above 30 FPS are intentionally refused. |
| `verify` reports no MCAP reader | Run `python3 -m pip install --user mcap`. |
| Video does not open in a desktop player | Validate/remux it with the FFmpeg commands above; elementary streams are not MP4 files. |
| `.partial` MCAP remains | The recording did not close cleanly. Preserve its log for diagnosis and do not publish it as a completed capture. |
| Preview is delayed | It is a CPU convenience preview. Close other GPU/camera applications or use `camera_viz` for the GPU path. |
| SchemaPusher exits immediately | A running OpenXR runtime is required; an old `cloudxr.env` file alone is insufficient. |
