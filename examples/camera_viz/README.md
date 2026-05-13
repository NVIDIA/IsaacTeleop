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

Build the wheel, run the setup script once, activate the venv:

```bash
cmake -B build -DBUILD_VIZ=ON
cmake --build build --target python_wheel --parallel

examples/camera_viz/scripts/setup_dev_env.sh           # adds --with-zed if you have the ZED SDK
source examples/camera_viz/.venv/bin/activate
```

`setup_dev_env.sh` creates `examples/camera_viz/.venv/`, installs the
IsaacTeleop wheel + every Python dep camera_viz / camera_streamer
needs (cupy, scipy, pyyaml, opencv-python, depthai, PyGObject), and
builds the native NVENC/NVDEC codec under `codec/`. Pass `--no-rtp` /
`--no-oakd` / `--no-v4l2` to skip extras, `--with-zed` to also pull in
pyzed via the ZED SDK's `get_python_api.py`. Re-run any time to upgrade.

### Workstation, local cameras

```bash
python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
```

Swap the config (`oakd.yaml`, `zed.yaml`, `synthetic.yaml`) for other
cameras.

### Robot → workstation over RTP

Edit `streaming.host` in the YAML to the workstation's IP. Then:

```bash
# Robot (sender):
python examples/camera_viz/camera_streamer.py examples/camera_viz/configs/v4l2.yaml

# Workstation (receiver) — set `source: rtp` in the YAML, then:
python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
```

`camera_streamer.py --host <IP>` overrides `streaming.host` for ad-hoc
testing.

### Loopback (one host, sender + viewer)

`scripts/loopback.sh <config.yaml>` runs both sides on `127.0.0.1`.
With the venv activated it just calls `python`; without one it falls
back to a slower per-invocation `uv run --with` chain.

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

Top-level `encoder: auto | nvenc | gstreamer` selects the NVENC backend.
`auto` picks the native NVENC codec on desktop and GStreamer
(`nvv4l2h264enc`) on Jetson — no config change needed when moving the
same YAML between platforms.

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
├── camera_viz.py        # receiver / viewer
├── camera_streamer.py   # robot-side RTP sender
├── pipeline/            # source ABC + threaded runner
├── placements/          # XR lock-mode strategies
├── sources/             # V4L2 / OAK-D / ZED / synthetic
├── transports/          # RTP H.264 sender + receiver
├── configs/             # one YAML per camera kind
└── scripts/             # setup_dev_env.sh + loopback.sh; robot installer later
```
