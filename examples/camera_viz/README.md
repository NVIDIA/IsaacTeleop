<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# camera_viz

Holoscan-free camera-feed visualizer for Isaac Teleop, built on
[Televiz](../../src/viz/). The teleop-side replacement for
[`examples/camera_streamer/`](../camera_streamer/)'s display path
(`HolovizOp` + `XrPlaneRenderer`), with the source / transport plumbing
deliberately scoped down to what the operator's HMD needs.

## Design points

- **Zero D2H/H2D in the hot path.** Sources produce GPU-resident frames
  (CuPy / PyTorch / NVDEC arrays) and feed them straight to QuadLayers
  via `__cuda_array_interface__`. The only mandatory upload is at a
  camera's hardware boundary (USB / network).
- **Render on its own thread.** `VizRunner` owns one render thread
  that pulls latest frames from each source and drives
  `session.render()`. VizSession's blocking calls release the GIL, so
  source producers run truly concurrently. Pairs cleanly with a
  `TeleopSession` on the main thread.
- **Light framework, not a DAG.** Linear source → display; no fan-out
  / fan-in. Plug in a new source by subclassing `FrameSource` and
  registering one factory case.
- **Placement is app policy.** Lock modes live here, not in viz_layers.

## Layout

```
camera_viz/
├── camera_viz.py        # display: opens cameras locally OR listens for RTP
├── camera_sender.py     # robot side: opens cameras locally and ships RTP
├── pipeline/            # framework: source ABC + threaded runner
├── placements/          # world / head / lazy locks (camera_plane.cpp port)
├── sources/             # GPU-resident frame producers
├── transports/          # RTP H.264 sender + receiver + NVENC/NVDEC wrappers
└── configs/             # example YAMLs (one per camera kind)
```

## Single YAML, two scripts

Each config under `configs/` describes the full pipeline: cameras, the
RTP transport for each, the receiver-side display settings. The same
file is consumed by both `camera_viz.py` (display) and `camera_sender.py`
(robot). Three knobs flip behavior:

- `source: local | rtp` (top-level, `camera_viz.py` only) — open cameras
  directly on this host, or listen for RTP streams produced by a
  matching `camera_sender.py` somewhere else.
- `display.mode: window | xr` — desktop window vs. headset.
- `streaming.host: <IP>` — sender target. Override with
  `camera_sender.py --host …` for ad-hoc testing.

## Lock modes

Ported 1:1 from `camera_streamer/operators/xr_plane_renderer/camera_plane.cpp`.
Parameter names and defaults match `CameraPlaneConfig`.

| Mode    | Behavior                                                              |
|---------|-----------------------------------------------------------------------|
| `world` | Snap in front of the user on first frame; never move again            |
| `head`  | 6-DoF follow — plane glued to the head every frame                    |
| `lazy`  | World-locked, but smoothly re-snaps when the user looks away or drifts |

Lazy-mode tuning knobs (XR placement YAML block):

| YAML key                  | Default | Meaning                                            |
|---------------------------|---------|----------------------------------------------------|
| `distance`                | `1.5`   | Meters in front of head when (re)placed            |
| `offset_x`                | `0.0`   | Lateral offset (right = +)                         |
| `offset_y`                | `0.0`   | Vertical offset (up = +)                           |
| `look_away_angle_deg`     | `45.0`  | Degrees off-axis that counts as "looking away"     |
| `reposition_distance`     | `0.5`   | Meters of drift before triggering reposition       |
| `reposition_delay_s`      | `0.5`   | How long the user must stay disengaged before move |
| `transition_duration_s`   | `0.3`   | Smoothstep duration for the re-snap                |

## Running

Local-only sanity check (no robot, no network):

```bash
# From the IsaacTeleop checkout, with a wheel already in build/wheels/:
uv run --with ./build/wheels/isaacteleop-*.whl \
       --with cupy-cuda12x --with pyyaml --with scipy \
       python examples/camera_viz/camera_viz.py examples/camera_viz/configs/synthetic.yaml

# XR 3-up comparison (world / lazy / head side-by-side):
uv run --with ./build/wheels/isaacteleop-*.whl \
       --with cupy-cuda12x --with pyyaml --with scipy \
       python examples/camera_viz/camera_viz.py examples/camera_viz/configs/synthetic_xr_3up.yaml
```

Real camera, local:

```bash
# v4l2 — add --with opencv-python; oakd — add --with depthai; zed — see ZED SDK install.
uv run --with ./build/wheels/isaacteleop-*.whl \
       --with cupy-cuda12x --with pyyaml --with opencv-python --with scipy \
       python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
```

RTP — two processes, the **same YAML** on both sides. Set
`streaming.host` to the workstation's IP, flip `source: rtp` for the
receiver:

```bash
# On the robot:
python examples/camera_viz/camera_sender.py examples/camera_viz/configs/v4l2.yaml --host 192.168.1.100

# On the workstation (edit configs/v4l2.yaml: `source: rtp` first):
python examples/camera_viz/camera_viz.py examples/camera_viz/configs/v4l2.yaml
```

Press Ctrl-C (window mode) or close the headset session (XR mode) to exit.
