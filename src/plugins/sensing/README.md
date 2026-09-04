<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SENSING GMSL camera setup

Driver provisioning for the SENSING **SG8A-AGON-G2Y-A1** carrier on a Jetson
AGX Orin — two Astra **SHW5G** modules over GMSL2, on JetPack 7.2.1 /
L4T R39.2.1.

Two halves: the setup scripts that provision the rig, and
`camera_plugin_sensing`, which captures through **SIPL** and either encodes
H.264 on the Jetson V4L2 engine or hands frames to another process as CUDA
memory ([CUDA IPC](#cuda-ipc)).

> **There are no `/dev/video*` nodes and no `nvargus-daemon`.** SIPL owns the
> sensors from userspace. If you are looking for `v4l2-ctl`, `trig_mode`, or a
> kernel module to `insmod`, none of them exist on this rig.

## What SIPL changes

| | Argus (old SG10A rig) | SIPL (this rig) |
|---|---|---|
| Sensor drivers | kernel `.ko`, loaded every boot | userspace `.so` in `/usr/lib/nvsipl_drv` |
| Device nodes | `/dev/video0..9` | none |
| Arbitration | `nvargus-daemon`, multi-client | in-process, **exclusive** |
| Per-boot step | `load_modules.sh` + systemd unit | none |
| Frame sync | PWM trigger + J19 strap | deserializer `fsyncMode: osc_manual` |
| Geometry | `--width/--height/--sensor-mode` | read from the platform config |
| Privilege | container user + `/tmp/argus_socket` | container user + two groups |

Exclusive ownership is the one behavioural regression: **`nvsipl_camera` and
`camera_plugin_sensing` cannot run at the same time.** Stop one before starting
the other.

## Why two scripts

Setup is genuinely two-sided, and neither half can do the other's job:

| | Host | Container |
|---|---|---|
| vendor `install.sh` (drivers, DTBO, NITO) | ✅ | ❌ |
| device-tree overlay, `jetson-io` | ✅ | ❌ |
| `usermod -aG i2c,gpio` | ✅ | ❌ |
| `--group-add` on the container | — | ✅ needs it |
| build SDKs to compile against | — | ✅ needs them |

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
src/plugins/sensing/setup_host.sh [--pkg DIR] [--install-drivers]
                                  [--groups] [--smoke-test] [--yes]
```

The package is autodetected under `~`, `~/Sensing/`, `/home/*/` and
`/opt/sensing/`; `--pkg` or `$SENSING_PKG_DIR` overrides.

**First install only** — `--install-drivers` runs the vendor `install.sh`
(SIPL userspace drivers, `.dtbo`, NITO ISP tuning), then stops. Select the
overlay and reboot before continuing:

```bash
sudo /opt/nvidia/jetson-io.py    # Configure Jetson AGX CSI Connector
                                 # -> Configure for compatible hardware
                                 # -> Jetson Sensing SG8A-AGON-G2Y-A1 SIPL GMSL2x8
sudo nvpmodel -m 0 && sudo jetson_clocks
```

**There is no per-boot step.** The vendor `install.sh` is copy-only — drivers
to `/usr/lib/nvsipl_drv`, the overlay to `/boot`, NITO files to
`/var/nvidia/nvcam/settings/sipl`. Nothing needs loading afterwards, which is
why `sensing-load.sh` and `sensing-camera.service` no longer exist.

### Groups, not root

SIPL needs **no root**, but it does need two supplementary groups beyond
`video`:

| Node | Group | Why |
|---|---|---|
| `/dev/i2c-9`, `/dev/i2c-10` | `i2c` | the two MAX96712 deserializers |
| `/dev/gpiochip0`, `/dev/gpiochip1` | `gpio` | deserializer power enable |

```bash
sudo usermod -aG i2c,gpio $USER   # then log out and back in
```

Omit either and SIPL fails with exactly one line:

```
Master SetPlatformConfig (Camera HAL) failed. status: 10
```

which names neither the node nor the permission. `verify.sh` diagnoses it
properly; that is most of why it exists.

## Container setup

```bash
src/plugins/sensing/setup_container.sh [--sdk-dir DIR] [--skip-sdk] [--yes]
```

Checks the container can reach the device nodes, and provisions the build SDKs:

- **Group access** — the one hard blocker. Add to the container's `runArgs`:
  ```jsonc
  "--group-add", "114",   // i2c
  "--group-add", "985"    // gpio
  ```
  Numeric gids, because the container has no matching group *names*; the kernel
  checks numbers. `setup_container.sh` prints the exact lines for your host.
- **Jetson Multimedia API** — `NvVideoEncoder` and `nvbufsurface.h`. Fetched
  automatically: the script parses the version out of `/etc/nv_tegra_release`
  and pulls that exact build from the public pool, so it matches the running
  BSP by construction. (It lives under `common/`, not `t234/`.)
- **SIPL API headers** — also fetched, but by URL rather than by package:
  `Jetson_SIPL_API_R<rel>_aarch64.tbz2` is published alongside the L4T release
  and is a public download. The URL derives from the same version string, with
  a scrape of the Jetson Linux release page as fallback. To install one by
  hand instead:
  ```bash
  sudo tar xf Jetson_SIPL_API_R39.2.1_aarch64.tbz2 -C /usr/src/
  ```
  Override the location with `SIPL_API_DIR=/path/to/jetson_sipl_api`.

## The plugin

```bash
cmake -B build -DBUILD_PLUGIN_SENSING=ON
cmake --build build --target camera_plugin_sensing
```

Start by asking the platform config what exists. This needs no hardware — the
query API only parses the driver database and the JSON:

```bash
./camera_plugin_sensing --list-sensors
```

The platform config is vendored at
[`configs/shw5g.json`](configs/shw5g.json) and resolved relative to the
executable, so the plugin runs without the vendor package on disk. Pass
`--platform-config=PATH` to point at a newer vendor drop instead — see
[`configs/README.md`](configs/README.md).

```
SHW5G_2: 2 sensor(s)
  sensor=0  SHW5G  2560x1984 @ 60 fps
  sensor=1  SHW5G  2560x1984 @ 60 fps
```

Then capture:

```bash
./camera_plugin_sensing \
    --add-stream=sensor=0,ipc=/tmp/sensing0.sock \
    --add-stream=sensor=1,ipc=/tmp/sensing1.sock
```

### `sensor=N` is the pipeline index, and it is not the obvious number

For `SHW5G_2` the GMSL link indices, the CSI virtual channels and the JSON's
`sensorInfo.id` are **all 2 and 3**. The SIPL pipeline index — what
`--add-stream sensor=N` takes — is **0 and 1**. The camera-HAL query adapter
renumbers sequentially per config.

Always take the number from `--list-sensors`. Do not read it out of the JSON.
(In the vendor's `S56C_1_SHF3L_2` config the two happen to coincide, which is
exactly why this is worth stating.)

### Geometry comes from the platform config

There is no `--width`, `--height`, `--fps` or `--sensor-mode`. SIPL has no
runtime mode index; resolution and frame rate are properties of the virtual
channel in the platform config, and the plugin sizes its buffers from what the
query reports. A flag that can disagree with the hardware is a bug class this
rig simply does not have.

### Encoding at 5 MP60

Two sensors at 2560×1984 @ 60 is 4.9× the pixel rate the 1080p30 defaults were
chosen for, so the codec settings moved with it:

| Setting | Value | Why |
|---|---|---|
| level | **5.2** | 1,190,400 MB/s exceeds Level 5.1's 983,040 by 21% |
| `--bitrate` | 40 Mbps | 0.13 bits/pixel; 20 Mbps was 0.066 |
| `--peak-bitrate` | 60 Mbps | VBR ceiling; pass `0` to select CBR |

80 Mbps for the pair, about 36 GB/hour.

## CUDA IPC

An `ipc=` stream serves RGBA8 frames as CUDA memory over a Unix socket, with no
encode. `camera_viz` consumes it with `type: cuda_ipc`. See
[`examples/camera_viz/README.md`](../../../examples/camera_viz/README.md).

### Pairing the two eyes

Both sensors are driven from one deserializer fsync generator, and every frame
carries `frameCaptureTSC` on a timebase shared across the rig. That value is
recorded in the MCAP metadata as `capture_tsc_ns`.

**Pair on `capture_tsc_ns`, not on the wrapper timestamps.** The wrapper stamps
are `CLOCK_MONOTONIC` taken after per-sensor conversion, so they carry each
sensor's own queueing jitter; the TSC does not.

### Testing without a camera

`sensing_ipc_testsrc` publishes a synthetic pattern on the same socket
protocol, so the whole consumer side can be exercised with the rig powered off.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `SetPlatformConfig (Camera HAL) failed. status: 10` | missing `i2c` or `gpio` group — run `verify.sh` |
| `no modules left in '<config>' after applying the link masks` | `--link-masks` does not match the config; copy it from the vendor docs |
| `cannot open NITO file .../SHW5G.nito` | vendor `install.sh` was never run on the host |
| `sensor=N is not a pipeline in '<config>'` | using the link index or the JSON id; run `--list-sensors` |
| capture hangs, no frames, no error | another SIPL client holds the hardware — stop `nvsipl_camera` |
| `ISP0 reconciled to colour standard ...` | the ISP delivered something the kernel cannot decode; see the note in `sipl_camera.cpp` |
| `Could not get EglImage from fd` / `Failed to create EGLImage` | `DISPLAY` names an X server Tegra EGL cannot drive |

### DISPLAY and the EGL vendor

Two X servers usually exist on this box: **`:1` is a real server** the Tegra
driver can drive, **`:99` is Xvfb** and it cannot. With both `10_nvidia.json`
and `50_mesa.json` installed, GLVND hands out *Mesa's* EGL whenever `DISPLAY`
names a server Tegra EGL cannot drive, and `NvBufSurfaceMapEglImage()` then
fails with `Could not get EglImage from fd`.

The container defaults to `DISPLAY=:99`, so anything that renders needs:

```bash
export DISPLAY=:1     # nvsipl_camera --egl-display, camera_viz, any viewer
```

`camera_plugin_sensing` is unaffected — it never renders and calls
`unsetenv("DISPLAY")` before its first EGL call, which selects the Tegra driver
regardless of what was set. Do not remove that line because the capture path
"has no display": `NvBufSurfaceMapEglImage()` is how a SIPL buffer reaches CUDA,
so EGL is on the critical path even headless.

The vendor smoke test is the reference for "is the rig itself alive":

```bash
sudo nvsipl_camera -t $PKG/query/sg8a_agth_g2a/shw5g.json -c SHW5G_2 \
                   -m "0x0000 0x1100" --enable-camera-hal -s -Z
```

Expect ~60 fps per sensor with zero drops. Remember to stop it before starting
the plugin.
