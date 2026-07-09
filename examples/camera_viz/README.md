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
| `oakd`      | OAK-D mono RGB / LEFT / RIGHT (stereo not yet wired) |
| `zed`       | ZED 2 / Mini / X One; mono or `stereo: true` (per-eye SDK retrieve, zero-copy GPU) |
| `video`     | Video-file replay (anything OpenCV/FFmpeg reads) — preview / testing without a camera. Loops by default; `stereo: true` splits side-by-side files into eyes (viewer only) |

Output: window or XR headset; one plane per camera, aspect-fit. Stereo cameras render true SBS in XR; window mode shows the left eye. XR placements: `world` / `head` / `lazy`.

---

## Setup (one-time)

```bash
examples/camera_viz/camera_viz.sh setup
source examples/camera_viz/.venv/bin/activate
```

`setup` installs `isaacteleop` (which bundles Televiz) and every other Python dep from PyPI into `.venv/` via `uv` (no `--system-site-packages`), builds the native NVENC/NVDEC codec, and probes system packages (GStreamer plugins, cairo / girepository headers, JetPack `cuda-nvrtc` + ld.so wiring). If anything's missing it prints the exact `apt-get` line and prompts `[y/N]` — `n` or non-interactive aborts. No need to build IsaacTeleop from source.

Flags: `--no-{v4l2,oakd,rtp}`, `--with-zed`, `--sender-only`, `--jetson`. Pass `--venv PATH` to install into an existing venv (symlinks `.venv` → PATH so `run` / `loopback` pick it up too).

> **Developing against a local build?** Pass `--wheel <path>` (e.g. `camera_viz.sh setup --wheel build/wheels/isaacteleop-*.whl`) to install a locally built wheel instead of the PyPI release. See the [build-from-source guide](../../docs/source/getting_started/build_from_source/index.rst).

---

## Mode 1 — Direct

```bash
./camera_viz.sh run configs/v4l2.yaml
```

Set `source: local`. Swap config for `oakd.yaml`, `zed.yaml`, `synthetic.yaml`, `synthetic_stereo.yaml`, `multi_camera.yaml`, `video.yaml` (file replay — point `path:` at any recording).

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
    stereo: false             # zed / synthetic / video only — per-eye capture + SBS XR
    # … type-specific fields (e.g. synthetic: disparity_px; video: path, loop)
    rtp:
      port: 5000              # left eye when stereo
      port_right: 5001        # required when stereo + source: rtp
      bitrate_mbps: 15
      # gop: 150              # default fps*5
      # gpu_id: 0             # multi-GPU pin

display:                      # camera_viz only
  mode: window | xr
  window: { width, height }
  xr:     { near_z, far_z }
  clear_color: [r, g, b, a]
  placements:
    cam:
      lock_mode: lazy         # world | head | lazy
      distance: 1.5
      offset_x: 0.0
      offset_y: 0.0
      # size: [w_m, h_m]
      # stereo_baseline_mm: 0  # stereo cams: 0 = both eyes share the world quad
                               # (parallax from the frames); ~65 = virtual IPD push
```

Multiple cameras → multiple `cameras:` entries; each gets its own `rtp.port` (plus `port_right` if stereo) and renders as its own plane.

## Lock modes (XR)

| Mode | Behavior |
|---|---|
| `world` | Placed once in front of you; stays put |
| `head`  | Follows your head every frame |
| `lazy`  | World-locked, re-snaps when you look away (default) |

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
