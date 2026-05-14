<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# camera_viz

Camera streaming + visualization on Televiz (`isaacteleop.viz`).

Two ways to use it:

1. **Direct**: workstation runs the viewer with cameras attached locally.
2. **Split**: robot runs the sender, ships RTP H.264 to a workstation receiver. Wired Ethernet only — the current sender doesn't handle packet loss / jitter beyond what GStreamer's stock RTP layer provides.

## Supported cameras

| YAML `type:` | Notes |
|---|---|
| `synthetic` | GPU test pattern — no hardware, useful for sanity checks |
| `v4l2` | USB / UVC — anything `v4l2-ctl --list-formats-ext` shows |
| `oakd` | OAK-D mono RGB / LEFT / RIGHT |
| `zed` | ZED 2 / Mini / X One, left-eye mono (stereo XR not wired yet) |

Output: window or XR headset; one plane per camera, aspect-fit by default. XR placements support `world` / `head` / `lazy` lock modes.

## Setup (one-time)

```bash
# Build the IsaacTeleop wheel.
cmake -B build -DBUILD_VIZ=ON
cmake --build build --target python_wheel --parallel

# Provision the camera_viz venv + native codec.
examples/camera_viz/camera_viz.sh setup
source examples/camera_viz/.venv/bin/activate
```

`setup` apt-installs missing `python3-gi` / GStreamer plugins on Debian/Ubuntu, builds the native NVENC/NVDEC codec under `codec/`, and creates `.venv/`. Flags: `--no-{v4l2,oakd,rtp}`, `--with-zed`, `--sender-only` (skip wheel + Vulkan), `--jetson` (JetPack cuda-nvrtc + symlink fixups).

---

## Mode 1 — Direct (cameras on the workstation)

Edit the config so `source: local`, plug cameras in, run:

```bash
./camera_viz.sh receive configs/v4l2.yaml      # any config in source: local mode
# or directly:
python camera_viz.py configs/v4l2.yaml
```

Swap config for `oakd.yaml`, `zed.yaml`, `synthetic.yaml`. Synthetic is the fastest sanity check (no hardware).

## Mode 2 — Split (robot → workstation over RTP, wired)

The robot sends RTP H.264; the workstation receives + renders. **Wired Ethernet only.** No retransmit, no FEC; one dropped packet means one corrupted frame until the next IDR (default every 5 s).

```bash
# 1. Set streaming.host in the YAML to the workstation's IP.
$EDITOR configs/v4l2.yaml

# 2. Deploy the sender to the robot as a systemd user service.
./camera_viz.sh deploy --host 10.0.0.5 --user nvidia configs/v4l2.yaml
# Add --password PW if you don't have SSH keys (requires sshpass).
# Add --no-service to stop after deps so you can run camera_streamer.py by hand first.

# 3. Run the viewer on the workstation.
./camera_viz.sh receive configs/v4l2.yaml      # flips source: rtp in a temp YAML

# Operate the service:
./camera_viz.sh service-logs    --host 10.0.0.5 --user nvidia
./camera_viz.sh service-status  --host 10.0.0.5 --user nvidia
./camera_viz.sh service-restart --host 10.0.0.5 --user nvidia
```

`deploy` rsyncs source, runs `setup --sender-only --jetson`, installs a systemd user unit at `~/.config/systemd/user/camera-streamer.service`, and enables `loginctl enable-linger` (one-time sudo).

The sender supervises per-camera retries forever — camera unplug, SDK errors, network blips all recover. The service never voluntarily exits.

### Loopback (sender + viewer on one host)

`./camera_viz.sh loopback configs/v4l2.yaml` runs both on `127.0.0.1`. Useful for testing the RTP path before involving a robot.

---

## Config

One YAML drives both ends. Top-level keys:

```yaml
source: local | rtp           # camera_viz only: open cameras or listen for RTP
streaming:
  host: 192.168.1.100         # workstation IP — used by camera_streamer in rtp mode
encoder: auto | native | gstreamer   # auto picks native NVENC on desktop, GStreamer on Jetson

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
      bitrate_mbps: 15        # tune for your uplink
      # gop: 150              # frames between IDRs; default fps*5
      # gpu_id: 0             # multi-GPU: pin encoder/decoder to a specific device

display:                      # camera_viz only
  mode: window | xr
  window: { width, height }
  xr: { near_z, far_z }
  clear_color: [r, g, b, a]   # default [0,0,0,0] (transparent)
  placements:
    cam:                      # keyed by camera YAML name
      lock_mode: lazy         # world | head | lazy
      distance: 1.5
      offset_x: 0.0
      offset_y: 0.0
      # size: [w_m, h_m]      # default: 1.0 m wide, height from camera aspect
```

Multiple cameras → multiple `cameras:` entries; each gets its own `rtp.port` and renders as its own plane.

## Lock modes (XR)

| Mode | Behavior |
|---|---|
| `world` | Place once in front of you; stays put |
| `head` | Follows your head every frame |
| `lazy` | World-locked, re-snaps when you look away (default) |

Lazy timing knobs: `look_away_angle_deg`, `reposition_distance`, `reposition_delay_s`, `transition_duration_s` under `placements.<name>`.

## Layout

```
camera_viz/
├── camera_viz.sh        # CLI: setup / loopback / receive / deploy / service-*
├── camera_viz.py        # receiver / viewer
├── camera_streamer.py   # robot-side RTP sender (per-camera supervisor, retries forever)
├── pipeline/            # source ABC + threaded runner
├── placements/          # XR lock-mode strategies
├── sources/             # V4L2 / OAK-D / ZED / synthetic / rtp_h264
├── transports/          # RTP sender + receiver, native + GStreamer encoders
├── codec/               # native NVENC/NVDEC pybind module
├── configs/             # one YAML per camera kind
└── scripts/
    ├── _install_deps.sh             # shared installer (used by setup + deploy)
    └── camera-streamer.service.in   # systemd unit template
```
