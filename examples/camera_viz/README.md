<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# camera_viz

Camera streaming and visualization for Isaac Teleop. Two scripts, one
config file:

- `camera_streamer.py` — runs on the **robot**; opens local cameras and
  ships frames as RTP H.264 over UDP.
- `camera_viz.py` — runs on the **workstation**; either listens for
  those RTP streams or opens cameras directly. Renders to a desktop
  window or to an XR headset.

Built on Televiz (`isaacteleop.viz`).

## Supported cameras

| Type | YAML `type:` | Notes |
|---|---|---|
| Synthetic GPU pattern | `synthetic` | No hardware; useful for sanity checks |
| USB / UVC / V4L2 | `v4l2` | Anything `v4l2-ctl --list-formats-ext` shows |
| OAK-D | `oakd` | Mono RGB / LEFT / RIGHT |
| ZED | `zed` | ZED 2 / Mini / X One; left-eye mono |

Stereo cameras (OAK-D / ZED) currently expose only one eye — full
stereo XR is pending a layer-side feature.

## Quick start

One script drives local development and remote (robot) deployment:

```bash
# Build the IsaacTeleop wheel first (one-time).
cmake -B build -DBUILD_VIZ=ON
cmake --build build --target python_wheel --parallel

# Then provision the camera_viz venv + native codec.
examples/camera_viz/camera_viz.sh setup
source examples/camera_viz/.venv/bin/activate
```

`setup` creates `examples/camera_viz/.venv/`, installs the IsaacTeleop
wheel and the Python deps camera_viz / camera_streamer need (cupy,
scipy, pyyaml, opencv-python, depthai), apt-installs the system
GStreamer + PyGObject bindings, and builds the native NVENC/NVDEC
codec under `codec/`. Flags: `--no-rtp` / `--no-oakd` / `--no-v4l2`
to skip extras, `--with-zed` for pyzed, `--sender-only` for a sender-
only host (skips wheel + vulkan deps).

### Workstation, local cameras

```bash
python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
```

Swap the config (`oakd.yaml`, `zed.yaml`, `synthetic.yaml`) for other
cameras.

### Robot → workstation over RTP

Edit `streaming.host` in the YAML to the workstation's IP. Then deploy
the sender as a systemd user service on the robot:

```bash
# Workstation, ship the sender to the robot:
./camera_viz.sh deploy --host 10.0.0.5 --user nvidia configs/v4l2.yaml
./camera_viz.sh service-logs --host 10.0.0.5 --user nvidia
./camera_viz.sh service-restart --host 10.0.0.5 --user nvidia

# Workstation, start the viewer:
./camera_viz.sh receive configs/v4l2.yaml
```

`receive` rewrites `source: rtp` in a temp config and runs `camera_viz.py`
— the receiver binds to `0.0.0.0:rtp.port`, so the sender's IP doesn't
need to be supplied here.

`deploy` rsyncs the source to `~/camera_viz/` on the robot, runs
`setup --sender-only` there, installs a systemd user unit at
`~/.config/systemd/user/camera-streamer.service`, and enables
`loginctl enable-linger` once so the service survives logout.

Add `--password PW` to all remote commands if you don't have SSH keys
set up (requires `sshpass`). The sender supervisor retries forever on
camera / SDK errors, so the service never voluntarily exits.

### Loopback (one host, sender + viewer)

`./camera_viz.sh loopback configs/v4l2.yaml` runs both sides on
`127.0.0.1`. Requires the local venv (`setup` first).

## Config

The same YAML drives both scripts. Top-level keys:

```yaml
source: local | rtp           # camera_viz only: open cameras locally, or listen for RTP
streaming:
  host: 192.168.1.100         # workstation IP — used by camera_streamer

cameras:
  - name: cam
    enabled: true
    type: v4l2                # v4l2 | oakd | zed | synthetic
    width: 2560
    height: 720
    fps: 30
    # … type-specific fields (device, resolution preset, etc.)
    rtp:
      port: 5000
      bitrate_mbps: 15        # camera_streamer's default; tune for your uplink
      profile: baseline       # baseline | main | high
      # gop: 150              # frames between IDRs; default fps*5 (ULL tuning)
      # encoder: auto         # per-camera override of the top-level encoder:

display:                      # camera_viz only
  mode: window | xr
  window: { width, height }
  xr: { near_z, far_z }
  clear_color: [r, g, b, a]
  placements:
    cam:                      # keyed by camera name
      lock_mode: lazy         # world | head | lazy
      # size: [width_m, height_m]   # default: 1.0 m wide, height from camera aspect
      distance: 1.5
      offset_x: 0.0
      offset_y: 0.0
```

Multiple cameras → multiple `cameras:` entries, each with its own
`rtp.port`. The streamer fans out to all of them; the viewer renders
each as its own plane.

Top-level `encoder: auto | native | gstreamer` selects the H.264 backend.
`auto` picks the native NVENC codec when its `.so` is importable, GStreamer
(`nvv4l2h264enc` on Jetson, `nvh264enc` / `x264enc` fallbacks) otherwise.

## Lock modes (XR display)

| Mode | Behavior |
|---|---|
| `world` | Place once in front of you; stays put |
| `head` | Follows your head every frame |
| `lazy` | World-locked, smoothly re-snaps when you look away (default) |

Lazy-mode timing — `look_away_angle_deg`, `reposition_distance`,
`reposition_delay_s`, `transition_duration_s` — defaults to
camera_streamer's tuning; override per-camera under `placements.<name>`.

## Layout

```
camera_viz/
├── camera_viz.sh        # local + remote CLI (setup/loopback/deploy/service-*)
├── camera_viz.py        # receiver / viewer
├── camera_streamer.py   # robot-side RTP sender (per-camera supervisor, retries forever)
├── pipeline/            # source ABC + threaded runner
├── placements/          # XR lock-mode strategies
├── sources/             # V4L2 / OAK-D / ZED / synthetic
├── transports/          # RTP H.264 sender + receiver
├── codec/               # native NVENC/NVDEC pybind module
├── configs/             # one YAML per camera kind
└── scripts/
    ├── _install_deps.sh             # shared installer (used by setup + deploy)
    └── camera-streamer.service.in   # systemd unit template
```
