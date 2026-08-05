<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# camera_viz

> Camera streaming + visualization on Televiz (`isaacteleop.viz`).

| Mode | What it does |
|---|---|
| **Direct** | Workstation runs the viewer with cameras attached locally. |
| **Split**  | Robot runs the sender, ships RTP H.264 to a workstation receiver. Wired Ethernet only. |

## Supported cameras

| YAML `type:` | Notes |
|---|---|
| `synthetic` | GPU test pattern — no hardware. `stereo: true` adds a `disparity_px` offset between eyes |
| `v4l2`      | USB / UVC — anything `v4l2-ctl --list-formats-ext` shows |
| `oakd`      | OAK-D RGB / LEFT / RIGHT; mono or `stereo: true` (GRAY8 over USB, GPU-broadcast to RGBA; `stereo_rgb` for color). Needs the Luxonis udev rule — see below |
| `orbbec_ego` | Ego PID 0x1201 stereo ColorLeft/ColorRight; native SDK capture with MJPEG or NVDEC H.264/H.265 |
| `zed`       | ZED 2 / Mini / X One; mono or `stereo: true` (per-eye SDK retrieve, zero-copy GPU) |
| `video`     | Video-file replay (anything OpenCV/FFmpeg reads) — preview / testing without a camera. Loops by default; `stereo: true` splits side-by-side files into eyes (viewer only) |

In XR mode the viewer **launches the CloudXR runtime + WSS proxy itself** — nothing to start separately (`--no-launch-cloudxr-runtime` reuses an external one; `--accept-eula` for the first run; `camera_viz.py --help` for the rest). Output: XR headset (default) or desktop window (`run CONFIG --mode window`); one surface per camera — a flat plane (default), a cylinder arc, or an equirect sphere (`placements.<name>.shape`, XR only for the curved shapes). Stereo cameras render true SBS in XR; window mode shows the left eye. Use `--stereo-debug sbs` with window mode to inspect both eyes side-by-side. XR placements: `world` / `head` / `lazy` / `gimbal`.

---

## Setup (one-time)

```bash
examples/camera_viz/camera_viz.sh setup
source examples/camera_viz/.venv/bin/activate
```

`setup` creates `.venv/` via `uv` (no `--system-site-packages`) and installs `isaacteleop[cloudxr]` — which bundles Televiz — plus every other Python dep. The `cloudxr` extra is not optional here: XR is the default mode and the viewer launches the runtime itself. It then probes system packages (cairo / girepository headers, GStreamer plugins under `--with-rtp`, JetPack `cuda-nvrtc` + ld.so wiring). If anything's missing it prints the exact `apt-get` line and prompts `[y/N]` — `n` or non-interactive aborts. No need to build IsaacTeleop from source.

camera_viz needs an `isaacteleop` new enough to carry the features it uses, so `setup` works down a ladder to get one: newest **final release** meeting that minimum; else newest **release candidate** (an rc is published from every release-branch commit, and PEP 440 keeps pre-releases out of a plain minimum-version specifier); else a **source build** of this checkout, after asking. Final releases win automatically whenever one qualifies. The minimum itself lives in `scripts/_install_deps.sh`.

On Ubuntu 22.04, full setup uses uv's managed Python 3.12, including its Python
development headers; **do not** install or add a PPA for `python3.12-dev` (that
package is not in Ubuntu 22.04). The prompt should list only Cairo,
gobject-introspection, and GStreamer dependencies as needed. `--sender-only`
uses the system Python instead and may correctly request its matching
`pythonX-dev` package.

The default Orbbec Ego configuration uses H.264 and native NVDEC. It requires
both a working NVIDIA driver **and** the NVIDIA CUDA Toolkit (`nvcc`); the CUDA
version printed by `nvidia-smi` reports driver capability and does not mean the
Toolkit is installed. Install the Toolkit for Ubuntu 22.04 from NVIDIA's
[CUDA installation guide](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html),
then verify and rerun setup:

```bash
nvcc --version
examples/camera_viz/camera_viz.sh setup --with-orbbec --orbbec-sdk-root /path/to/OrbbecSDK
```

If NVDEC is intentionally unavailable, set `format: mjpg` in
`configs/orbbec_ego.yaml`. MJPEG is decoded by OrbbecSDK and uploaded to CuPy;
H.264/H.265 are unavailable until the native codec builds successfully.

`setup` also safely retries a codec configuration that previously ran before
the Toolkit was installed: it clears only CMake's generated cache and preserves
the downloaded NVIDIA Video Codec SDK. Do not delete
`examples/camera_viz/codec/build/` merely to retry; rerun `setup` instead.
An interrupted SDK download is detected by checksum, removed, and retried; a
network error is reported directly rather than as a later missing-source error.

If the prompted `apt-get install` reports unmet dependencies and suggests
`apt --fix-broken install`, the host package database is inconsistent rather
than a camera_viz dependency being unavailable. Review the repair first, then
repair it and rerun setup:

```bash
sudo apt-get -s --fix-broken install  # simulation: inspect changes first
sudo apt --fix-broken install
```

Flags: `--no-{v4l2,oakd,rtp}`, `--with-zed`, `--with-orbbec --orbbec-sdk-root PATH`, `--sender-only`, `--jetson`. Pass `--venv PATH` to install into an existing venv (symlinks `.venv` → PATH so `run` / `loopback` pick it up too).

Flags: `--no-{v4l2,oakd}`, `--with-rtp` (split mode / `loopback`; implied by `--sender-only`), `--with-zed`, `--sender-only`, `--jetson`. Pass `--venv PATH` to install into an existing venv (symlinks `.venv` → PATH so `run` / `loopback` pick it up too).

> **OAK-D?** The camera needs a udev rule, or `depthai` reports `Insufficient permissions to communicate with X_LINK_UNBOOTED device` and never finds it. `setup` prompts to install one when an OAK-D is attached and no rule covers it; declining is not fatal. By hand:
> ```bash
> echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules
> sudo udevadm control --reload-rules && sudo udevadm trigger   # then replug
> ```

> **Developing against a local build?** Pass `--wheel <path>` (e.g. `camera_viz.sh setup --wheel build/wheels/isaacteleop-*.whl`) for a wheel you already built, or `--build-from-source` to build this checkout without asking. See the [build-from-source guide](../../docs/source/getting_started/build_from_source/index.rst).

---

## Mode 1 — Direct

```bash
./camera_viz.sh run configs/v4l2.yaml                  # XR headset (default)
./camera_viz.sh run configs/v4l2.yaml --mode window    # desktop window instead
```

Set `source: local`. Swap config for `oakd.yaml`, `zed.yaml`, `realsense.yaml`, `synthetic.yaml`, `synthetic_stereo.yaml`, `synthetic_xr_3up.yaml`, `multi_camera.yaml`, `replay.yaml` (file replay — point `path:` at any recording).
Set `source: local`. Swap config for `oakd.yaml`, `zed.yaml`, `realsense.yaml`, `synthetic.yaml`, `synthetic_stereo.yaml`, `synthetic_xr_3up.yaml`, `multi_camera.yaml`, `replay.yaml` (file replay — point `path:` at any recording), or `orbbec_ego.yaml`. The Orbbec configuration requires the optional native binding:

```bash
./camera_viz.sh setup --with-orbbec --orbbec-sdk-root /absolute/path/to/OrbbecSDK
./camera_viz.sh run configs/orbbec_ego.yaml --mode window
# Optional desktop stereo pairing/disparity check:
./camera_viz.sh run configs/orbbec_ego.yaml --mode window --stereo-debug sbs
```

## Mode 2 — Split (robot → workstation, RTP)

> ⚠ **Wired only.** No retransmit / FEC; one lost packet = one corrupted frame until the next IDR (default 5 s).

```bash
# YAML: set source: rtp. Leave streaming.host as-is — overridden at deploy time.
$EDITOR configs/v4l2.yaml

# Export creds once per shell (keeps password out of history / argv):
export REMOTE_HOST=10.0.0.5 REMOTE_USER=nvidia
read -s REMOTE_PASSWORD && export REMOTE_PASSWORD   # if no SSH keys
export STREAMING_HOST=10.0.0.42                      # workstation IP

./camera_viz.sh deploy configs/v4l2.yaml             # full deploy + systemd
./camera_viz.sh run    configs/v4l2.yaml             # viewer on the workstation
./camera_viz.sh service-{status,logs,restart}        # operate the unit
```

What `deploy` does:

1. `rsync` source to `~/camera_viz` on the robot.
2. `ssh -t` runs `_install_deps.sh --sender-only --jetson`; the `[y/N]` prompt fires for any missing apt / CUDA wiring on the Jetson.
3. Renders `~/.config/systemd/user/camera-streamer.service`. `--streaming-host` (or `$STREAMING_HOST`) injects `--host IP` into the unit's `ExecStart`; the YAML on disk stays untouched.
4. `sudo loginctl enable-linger` (one-time) + `systemctl --user enable --now`.

`--no-service` stops after step 2. The sender retries forever (unplug, SDK errors, network blips); the service never voluntarily exits.

### Loopback

`./camera_viz.sh loopback configs/v4l2.yaml` runs sender + viewer on `127.0.0.1`. Quickest way to smoke-test the RTP path.

---

## Config

```yaml
source: local | rtp           # camera_viz only
streaming:
  host: 192.168.1.100         # workstation IP (override at deploy time)
encoder: auto | native | gstreamer

cameras:
  - name: cam
    enabled: true
    type: v4l2                # v4l2 | oakd | zed | synthetic | video
    width: 2560               # video: optional — defaults to the file's size
    height: 720
    fps: 30
    stereo: false             # zed / oakd / synthetic / video — per-eye capture + SBS XR
    # … type-specific fields (e.g. synthetic: disparity_px; video: path, loop)
    rtp:
      port: 5000              # left eye when stereo
      port_right: 5001        # required when stereo + source: rtp
      bitrate_mbps: 15
      # gop: 150              # default fps*5
      # gpu_id: 0             # multi-GPU pin

display:                      # camera_viz only
  mode: xr | window           # default: xr
  window: { width, height }
  xr:     { near_z, far_z }
  clear_color: [r, g, b, a]
  placements:
    cam:
      lock_mode: lazy         # world | head | lazy | gimbal
      distance: 1.5
      offset_x: 0.0
      offset_y: 0.0
      # size: [w_m, h_m]
      # stereo_baseline_mm: 0  # stereo cams: 0 = both eyes share the world quad
                               # (parallax from the frames); ~65 = virtual IPD push
      # shape: quad            # quad (default) | cylinder | equirect — XR only for
                               # the curved shapes
      # compositor: openxr     # openxr (default) | televiz — quads only
      # cylinder_radius_m: 2.0 # cylinder: viewing distance to the arc
      # cylinder_angle_deg: 90 # cylinder: visible arc width
```

Multiple cameras → multiple `cameras:` entries; each gets its own `rtp.port` (plus `port_right` if stereo) and renders as its own plane.

## Lock modes (XR)

| Mode | Behavior |
|---|---|
| `world`  | Placed once in front of you; stays put |
| `head`   | Follows your head every frame |
| `gimbal` | Translation follows you, yaw stays as first seen — walk and it comes along, turn your head and you look around it. For wide cylinder feeds |
| `lazy`   | World-locked, re-snaps when you look away (default) |

Lazy knobs under `placements.<name>`: `look_away_angle_deg`, `reposition_distance`, `reposition_delay_s`, `transition_duration_s`.

---

## Layout

```
camera_viz/
├── camera_viz.sh        — CLI: setup / loopback / run / deploy / service-*
├── camera_viz.py        — receiver / viewer
├── camera_streamer.py   — robot-side RTP sender (per-camera supervisor)
├── pipeline/            — source ABC + threaded runner
├── placements/          — XR lock-mode strategies
├── sources/             — V4L2 / OAK-D / ZED / synthetic / video replay / rtp_h264
├── transports/          — RTP sender + receiver, native + GStreamer
├── codec/               — native NVENC/NVDEC pybind module
├── configs/             — one YAML per camera kind
├── test_data/           — sample replay clip (Git LFS)
└── scripts/
    ├── _install_deps.sh             — installer (setup + deploy)
    └── camera-streamer.service.in   — systemd unit template
```

---

## Sharing the XR session with TeleopSession

Only one OpenXR session is allowed per process. `VizSession` can own it and hand its live handles to `TeleopSession` / `DeviceIOSession` so they skip creating their own:

```python
import isaacteleop.viz as viz
from teleopcore.oxr import OpenXRSessionHandles

cfg = viz.VizSessionConfig()
cfg.mode = viz.DisplayMode.kXr
# Aggregate the XR extensions downstream trackers need (e.g.
# XR_NVX1_action_context for ControllerTracker) so they're present
# on the XrInstance we're about to create.
cfg.required_extensions = DeviceIOSession.get_required_extensions(trackers)
viz_session = viz.VizSession.create(cfg)

# Pass the live handles into TeleopSession via its config.
config = TeleopSessionConfig(
    app_name="MyApp",
    pipeline=pipeline,
    oxr_handles=OpenXRSessionHandles(*viz_session.get_oxr_handles()),
)
with TeleopSession(config) as session:
    ...
```

`viz_session.get_oxr_handles()` returns `(instance, session, space, proc_addr)` as raw `uint64`s, or `None` outside `kXr`.
