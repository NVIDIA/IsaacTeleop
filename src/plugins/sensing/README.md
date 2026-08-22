<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SENSING GMSL camera setup

Driver provisioning for the SENSING **SG10A-AGON-G2M-A1** carrier on a Jetson
AGX Orin — one Astra **S56C** plus up to six **SHF3L/SHF3H** cameras over GMSL2,
on JetPack 6.2 / L4T R36.4.3.

Two halves: the setup scripts that bring the drivers up, and
`camera_plugin_sensing`, which captures through libargus and either encodes
H.264 on the Jetson V4L2 engine or hands frames to another process as CUDA
memory ([CUDA IPC](#cuda-ipc)).

> **Argus needs NVIDIA's EGL, and `DISPLAY` can silently deny it.** If `DISPLAY`
> names an X server Tegra EGL cannot drive — Xvfb, X11 forwarding — GLVND hands
> the process Mesa's EGL and every Argus-to-CUDA path fails. See
> [EGL vendor](#egl-vendor-selection).

Vendor package (the `.ko`, `Image`, `.dtbo` and ISP files this wraps):
<https://github.com/SENSING-Technology/nvidia-jetson-camera-drivers>

## Why two scripts

Setup is genuinely two-sided, and neither half can do the other's job:

| | Host | Container |
|---|---|---|
| `insmod` sensor drivers | ✅ host kernel | ❌ |
| device-tree overlay, `jetson-io` | ✅ | ❌ |
| POC / PWM `devmem` writes | ✅ | ❌ |
| `nvargus-daemon` | ✅ runs here | ❌ |
| `/tmp/argus_socket` bind mount | — | ✅ needs it |
| Argus headers to build against | apt | ✅ needs them |

```bash
# on the Jetson host
src/plugins/sensing/setup.sh          # -> setup_host.sh

# inside the devcontainer
src/plugins/sensing/setup.sh          # -> setup_container.sh

# anywhere, read-only
src/plugins/sensing/verify.sh
```

`setup.sh` auto-detects the context; `--host` / `--container` override it.
Every script announces **exactly which privileged actions it will take** in a
coloured banner before the first `sudo` prompt, and asks before each optional
one. `--yes` accepts them all; a non-interactive stdin declines them all.

## Host setup

```bash
src/plugins/sensing/setup_host.sh [--pkg DIR] [--fps 30] [--free-run|--trigger-sync]
                                  [--install-drivers] [--service|--no-service] [--yes]
```

The package is autodetected under `~/Sensing/`, `~`, `/home/*/Sensing/` and
`/opt/sensing/`; `--pkg` or `$SENSING_PKG_DIR` overrides.

**First install only** — `--install-drivers` runs the vendor `install.sh`
(kernel `Image`, `.dtbo`, ISP tuning), then stops. Select the overlay and
reboot before continuing:

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py    # Configure Jetson AGX CSI Connector
                                 # -> Jetson Sensing SG10A_AGON_G2M_A1 S56Cx1 SHF3Lx6
```

**Every boot** — the vendor `install.sh` never copies the sensor `.ko` files
into `/lib/modules`, so nothing auto-loads them and `/dev/video*` is empty after
each reboot until `load_modules.sh` runs. That is the single most common cause
of "the cameras stopped working". `setup_host.sh` runs it, then offers to
install `sensing-camera.service` so it happens at boot.

The unit is ordered `After=basic.target` / `Before=nvargus-daemon.service` —
**not** `After=multi-user.target`, which races: `nvargus-daemon` is itself part
of `multi-user.target`, and a daemon that starts before the sensors exist
enumerates an empty camera list and never retries.

### Trigger mode

`load_modules.sh` leaves sensors slaved to the carrier's PWM trigger
(`trig_mode=1` on S56C, `2` on SHF3L). That only fires when **J19 pins 2 and 4
are strapped together**. Without the strap the camera opens fine and then
delivers no frames — a failure that looks like a software hang.

`--free-run` (the default) sets `trig_mode=0` on every node. Use
`--trigger-sync` to keep vendor behaviour when the strap is fitted and you need
cross-camera sync.

## Container setup

```bash
src/plugins/sensing/setup_container.sh [--build-argus] [--argus-include DIR] [--yes]
```

Checks the container can *consume* the host's drivers, and fixes what it can:

- **`/tmp/argus_socket`** — the one hard blocker. `libnvargus_socketclient`
  reaches `nvargus-daemon` through it, and a container gets its own `/tmp` even
  when `/tmp/.X11-unix` is bind-mounted. Add to `runArgs`:
  ```jsonc
  "-v", "/tmp/argus_socket:/tmp/argus_socket"
  ```
  and rebuild the container. Nothing in the container can work around this.
- **Argus headers** — `nvidia-l4t-jetson-multimedia-api` is usually not
  installable in a container (no L4T apt repo). If the tree is found elsewhere,
  the script offers to symlink it to `/usr/src/jetson_multimedia_api/argus`,
  which is the path both `camera_viz/argus/build.sh` and
  `camera_viz/scripts/_install_deps.sh` hardcode.
- `v4l-utils`, EGL headers, `nvcc`, and `argus_camera` on `PATH`.

## The plugin

```bash
cmake -B build -DBUILD_PLUGIN_SENSING=ON
cmake --build build --target camera_plugin_sensing --parallel
```

Both dependencies live outside the repo. On a Jetson they come from
`sudo apt install nvidia-l4t-jetson-multimedia-api`; in a container, copy the
tree in and point CMake at it:

```bash
cmake -B build -DBUILD_PLUGIN_SENSING=ON \
    -DARGUS_INCLUDE_DIRS=$HOME/Sensing/argus/include \
    -DJETSON_MMAPI_DIR=$HOME/Sensing/jetson_multimedia_api
```

`sensor=` is the **Argus sensor id**, not the `/dev/videoN` number — see
[the mapping below](#argus-sensor-ids-are-not-devvideo-numbers).

```bash
./build/src/plugins/sensing/camera_plugin_sensing \
    --add-stream=sensor=2,output=./left.h264 \
    --add-stream=sensor=3,output=./right.h264 \
    --mcap-filename=./meta.mcap
```

`--collection-prefix` pushes the same metadata over OpenXR instead; the two are
mutually exclusive. `--help` lists the capture and encoder knobs.

## CUDA IPC

`ipc=<socket>` on a stream serves that sensor's frames to another process as
**CUDA device memory** — RGBA8, no encode, no host round-trip. It is
independent of `output=`; give one, the other, or both. An `ipc`-only stream
never starts an encoder:

```bash
./build/src/plugins/sensing/camera_plugin_sensing \
    --add-stream=sensor=2,ipc=/tmp/sensing2.sock

# consume it
cd examples/camera_viz && ./camera_viz.sh run configs/cuda_ipc.yaml
```

The producer allocates a ring of frame slots in one shared allocation and hands
the consumer a file descriptor for it; per frame it copies into a free slot and
sends a 24-byte ready message. The consumer maps the allocation once and reads
slots in place, releasing each one when it moves on, so the producer never
overwrites a slot that is still being read. A consumer that falls behind gets
frames dropped rather than stalling capture. One consumer at a time — the
latest connection wins, so the viewer can restart without restarting the
plugin. Measured at 1920×1080 on an AGX Orin: ~1 ms producer-to-consumer,
60 fps sustained.

**Legacy CUDA IPC does not work on Tegra, and fails misleadingly.**
`cudaIpcGetMemHandle` returns `cudaSuccess` in this process, then the consumer's
`cudaIpcOpenMemHandle` fails with `cudaErrorInvalidValue`. The working route is
the virtual-memory-management API — `cuMemCreate` +
`cuMemExportToShareableHandle` to a POSIX fd, passed over the Unix socket with
`SCM_RIGHTS`. Do not rewrite this back to `cudaIpcMemHandle_t`.

Wire format is in [`core/cuda_ipc_protocol.hpp`](core/cuda_ipc_protocol.hpp);
the consumer re-declares it in
[`sources/cuda_ipc.py`](../../../examples/camera_viz/sources/cuda_ipc.py), so
the two change together.

### Testing without a camera

`sensing_ipc_testsrc` publishes an animated pattern over the same protocol, so
the consumer can be developed with no camera attached. It needs CUDA only — no
Argus, no encoder:

```bash
cmake --build build --target sensing_ipc_testsrc
./build/src/plugins/sensing/sensing_ipc_testsrc --socket=/tmp/sensing2.sock \
    --width=1920 --height=1080 --fps=60
```

Each frame carries its 16-bit frame number as a binary bar across the top, so a
stale or torn frame is visible rather than merely suspected — the
[camera_viz tests](../../../examples/camera_viz/tests/test_cuda_ipc_source.py)
assert on it.

### Playback

The output is raw Annex-B H.264 with no container and no timestamps, so a
player has to be told the frame rate:

```bash
ffplay -f h264 left.h264
ffmpeg -f h264 -framerate 30 -i left.h264 -c copy left.mp4   # -framerate must match --fps
```

On the Jetson, GStreamer decodes it on the hardware engine that wrote it:

```bash
gst-launch-1.0 filesrc location=left.h264 ! h264parse ! nvv4l2decoder ! nv3dsink
```

To check a file without any tools installed, the 5th byte after each
`00 00 01` start code carries the NAL type in its low 5 bits — a healthy
recording opens `67` (SPS), `68` (PPS), `65` (IDR):

```bash
xxd -l 16 left.h264
```

The MCAP sidecar holds one `core.FrameMetadataSensingRecord` per frame on
channel `sensing_metadata/sensor<N>`. Its binary schema is embedded, so
`mcap cat --json meta.mcap` decodes it without any Isaac headers.

## Status

| Stage | State |
|---|---|
| V4L2 M2M encoder (`NvVideoEncoder`) | works — opens, negotiates NV12M→H264, CBR/GOP applied |
| MCAP + OpenXR metadata | works |
| CUDA IPC publish + camera_viz consume | works — verified end to end against `sensing_ipc_testsrc` |
| Argus capture (S56C, `STREAM_TYPE_EGL`) | works — 1920x1080 into CUDA, with NVIDIA EGL selected |

### EGL vendor selection

`ArgusCamera` consumes `STREAM_TYPE_EGL` via `cuEGLStreamConsumerConnect`, and
that works under multi-process Argus — but only when the process resolves EGL to
NVIDIA's driver. GLVND picks the vendor from `DISPLAY`, and Tegra's EGL cannot
drive an Xvfb or forwarded X server, so it loses the probe to Mesa. Same binary,
same daemon, same sensor:

| `EGL_VENDOR` | `IEGLOutputStream::getEGLStream()` |
|---|---|
| `NVIDIA` | valid handle |
| `Mesa Project` | `EGL_NO_STREAM_KHR` |

Multi-process Argus is not the problem, and `STREAM_TYPE_BUFFER` is not required
to fix it. `NvBufSurfaceMapEglImage` fails the same way for the same reason
("Failed to create EGLImage"), so a buffer-stream rewrite would have hit the
identical wall.

`main()` therefore calls `unsetenv("DISPLAY")` before the first EGL call — this
process captures and never renders, and `libnvbufsurface` resolves its own
display via `eglGetDisplay(EGL_DEFAULT_DISPLAY)`, so the choice cannot be made
per-call. `ArgusCamera` additionally refuses to start on a non-NVIDIA vendor
rather than failing later with a misleading Argus error.

## Streaming

Two sensor families, two paths — the difference is not cosmetic:

| Camera | Nodes | Resolution | Output | camera_viz `type:` |
|---|---|---|---|---|
| Astra S56C | `video0`–`video3` | 1920×1080 (`sensor_mode=0`) | **RAW/Bayer** | `argus` |
| SHF3L/SHF3H | `video4`–`video9` | 1920×1536 (`sensor_mode=2`) | **YUV** | `v4l2` |

The S56C needs the ISP, so it must go through Argus. The SHF3L is already
ISP-processed on the module and works with the stock V4L2 source today.

For SHF3L, the stock [`examples/camera_viz/configs/v4l2.yaml`](../../../examples/camera_viz/configs/v4l2.yaml)
works as-is — point `device:` at the node from the table above and set
`1920x1536`.

For S56C, [`configs/argus_s56c.yaml`](configs/argus_s56c.yaml) carries the
Argus-specific knobs. It needs the native Argus source
(`examples/camera_viz/argus/`), which arrives with the Argus camera support PR;
`setup_container.sh` reports whether it is present.

### Argus sensor ids are not `/dev/video` numbers

Argus enumerates in device-tree module order. On this overlay:

| `sensor_id` | badge | `sensor_id` | badge |
|---|---|---|---|
| 0 | `cam7_frontright` | 5 | `cam1_bottomright` |
| 1 | `cam6_frontleft` | 6 | `cam2_centerleft` |
| 2 | `cam9_topcenter` | 7 | `cam3_centerright` |
| 3 | `cam8_bottomcenter` | 8 | `cam4_topleft` |
| 4 | `cam0_bottomleft` | 9 | `cam5_topright` |

Ids 0–3 are the S56C group, 4–9 the SHF3L ports. Re-derive after any overlay
change:

```bash
for i in $(seq 0 9); do
  printf '%s ' "$i"; cat /proc/device-tree/tegra-camera-platform/modules/module$i/badge; echo
done
```

## Troubleshooting

Run `verify.sh` first — it names the fixing script for each failure.

| Symptom | Cause |
|---|---|
| No `/dev/video*` after reboot | Drivers not loaded. Run `setup_host.sh`, then install the service. |
| Camera opens, no frames | Sensor slaved to an absent trigger. `setup_host.sh --free-run`. |
| Argus finds no cameras | `nvargus-daemon` started before the drivers. `sudo systemctl restart nvargus-daemon`. |
| `argus_camera: command not found` in container | It is installed at `/usr/local/bin` on the *host*, which is container-local. `setup_container.sh` offers to link a built copy. |
| `insmod: invalid module format` | Kernel is not `5.15.148-tegra`; the prebuilt `.ko` files will not load. |
| `EGL_NO_STREAM_KHR`, or `NvBufSurfaceMapEglImage` "Failed to create EGLImage" | EGL resolved to Mesa, not NVIDIA. Unset `DISPLAY`, or point it at an X server Tegra EGL can drive. Check with `eglQueryString(dpy, EGL_VENDOR)`. |
| `Connection refused` on every Argus call, right after restarting `nvargus-daemon` | The container bind-mounts `/tmp/argus_socket` as a *file*; the daemon unlinks and recreates it, so the mount pins a deleted inode (`grep argus /proc/self/mountinfo` shows `//deleted`). Mount the host's `/tmp` and symlink instead, or restart the container. |
| `/tmp/argus_socket` is a *directory* | The container started before `nvargus-daemon`, so Docker created the missing bind source. `sudo rmdir /tmp/argus_socket && sudo systemctl restart nvargus-daemon`. |
| `bmi088 ... softreset failed` at boot | The IMU probed before camera power came up. Harmless; `load_modules.sh` reloads it. |
