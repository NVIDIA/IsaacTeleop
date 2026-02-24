<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Camera Streamer

Multi-camera H.264 streaming for teleoperation. Supports ZED (stereo, NVENC), OAK-D (mono, VPU), and V4L2 (USB/HDMI) cameras on Jetson and x86_64.

Two modes of operation:
- **Local** (`source: local`): cameras opened directly on the same machine as the display -- lowest latency, single machine.
- **RTP** (`source: rtp`): sender streams H.264 over the network, receiver decodes and displays -- for robot-to-workstation setups.

## Quick Start

```bash
# Build the Docker image (two-step: base image + C++ operators with GPU)
./camera_streamer.sh build

# Interactive dev shell (host source mounted, edits reflected immediately)
./camera_streamer.sh run-container

# Local mode: open cameras directly and display
python3 teleop_camera_app.py --source local --mode monitor

# RTP mode: sender on robot, receiver on workstation
python3 teleop_camera_sender.py --host 192.168.1.100   # on robot
python3 teleop_camera_app.py --source rtp --mode monitor  # on workstation
```

## Source Mode

Set the top-level `source` field in your YAML config:

```yaml
source: "local"     # "rtp" or "local"
```

Or override via CLI: `python3 teleop_camera_app.py --source local`

| Mode | Description |
|---|---|
| `local` | Open cameras directly on this machine. No sender needed. Lowest latency. |
| `rtp` | Receive H.264 streams from `teleop_camera_sender.py` running on another machine. |

## Commands

| Command | Description |
|---|---|
| `build [--sender-only]` | Build Docker image (encoder + decoder + XR by default) |
| `run-container` | Interactive shell for dev/testing (host source mounted) |
| `deploy` | Start persistent container with `--restart unless-stopped` |
| `list-cameras` | List connected OAK-D and ZED cameras |
| `logs` | Follow container logs |
| `stop` | Stop the container |
| `restart` | Restart the container (picks up config changes) |
| `clean` | Remove Docker images |

## Modes

### Dev mode (`run-container`)

Mounts the host `camera_streamer/` directory into the container. Python and config edits on the host are reflected immediately — no rebuild needed. Built C++ libs live at `build/python/` on the host from the build step.

If the container is already running, a second `run-container` call attaches to it (`docker exec`).

### Production mode (`deploy`)

Uses the baked-in Docker image with `--restart unless-stopped`. The config file is bind-mounted so you can edit it on the host and restart without rebuilding.

```bash
./camera_streamer.sh deploy --receiver-host 192.168.1.100
vim config/multi_camera.yaml           # edit config
./camera_streamer.sh restart            # picks up changes
```

## Build Details

The build uses a two-step process because NVENC/NVDEC libraries require the GPU driver at compile time:

1. `docker build` creates the base image (Holoscan SDK + deps + source)
2. `docker run --runtime nvidia` compiles C++ operators inside a container, then `docker commit` captures the result

The `build/` directory is mounted from the host so cmake cache, FetchContent downloads, and object files persist across builds (incremental rebuilds are fast).

## Camera Configuration

Edit a config file under `config/` (e.g. `config/multi_camera.yaml`). Each camera has a name, type, and one or more streams with unique ports and stream IDs. Sample configs:

| Config | Description |
|---|---|
| `config/multi_camera.yaml` | 1 stereo ZED + 2 mono OAK-D (default) |
| `config/single_camera.yaml` | Single mono OAK-D |
| `config/v4l2.yaml` | Single V4L2 camera (USB/HDMI capture) |

### ZED Camera

Outputs BGRA frames on GPU, encoded to H.264 via NVENC. Supports mono and stereo.

```yaml
cameras:
  head:
    enabled: true
    type: zed
    stereo: true
    serial_number: 38674920    # from list-cameras, or 0 for first available
    resolution: "HD720"        # HD2K, HD1080, HD720, VGA
    fps: 30
    streams:
      left:  { stream_id: 0, port: 5000, bitrate_mbps: 15 }
      right: { stream_id: 1, port: 5001, bitrate_mbps: 15 }
```

### OAK-D Camera

H.264 encoded on-device by the VPU — no GPU encoding needed. Supports mono and stereo.

```yaml
cameras:
  wrist:
    enabled: true
    type: oakd
    stereo: false
    device_id: "19443010F1A6327E00"  # from list-cameras
    width: 1280
    height: 720
    fps: 30
    streams:
      mono: { stream_id: 2, port: 5002, bitrate_mbps: 10 }
```

### V4L2 Camera (USB, HDMI capture, etc.)

Any V4L2-compatible device (`/dev/videoN`). Frames are captured by Holoscan's built-in `V4L2VideoCaptureOp` and encoded to H.264 via NVENC. Requires NVENC (same as ZED). Mono only.

```yaml
cameras:
  usb_cam:
    enabled: true
    type: v4l2
    stereo: false
    device: "/dev/video0"
    width: 1280
    height: 720
    fps: 30
    streams:
      mono: { stream_id: 4, port: 5004, bitrate_mbps: 10 }
```

| Field | Description |
|---|---|
| `device` | V4L2 device path (e.g., `/dev/video0`) |
| `width` / `height` | Capture resolution |

### Finding Camera Serial Numbers

```bash
./camera_streamer.sh list-cameras
```

## Platform Notes

| | Jetson Thor | Jetson Orin | x86_64 (Ubuntu) |
|---|---|---|---|
| **ZED cameras** | NVENC H.264 | No NVENC — use OAK-D | NVENC H.264 |
| **OAK-D cameras** | VPU encoding | VPU encoding | VPU encoding |
| **V4L2 cameras** | NVENC H.264 | No NVENC | NVENC H.264 |
| **Base image** | `holoscan:v3.11.0-cuda13` | TBD | `holoscan:v3.11.0-cuda12-dgpu` |

## Troubleshooting

```bash
./camera_streamer.sh list-cameras       # verify cameras are detected
./camera_streamer.sh logs               # check container output
sudo ufw allow 5000:5010/udp            # open UDP ports on receiver
```

- **Camera not found**: Check USB connection. Run `list-cameras` to verify detection. If `X_LINK_DEVICE_ALREADY_IN_USE`, another process has the camera — stop it first.
- **ZED won't open**: Ensure USB 3.0 cable and port.
- **No video on receiver**: Check `--receiver-host` IP. Verify firewall allows UDP on configured ports.
- **GLFW / display errors**: Run `run-container` (passes `DISPLAY` and X11 socket). Headless sender (`deploy`) doesn't need a display.
- **Stack size warning**: The script passes `--ulimit stack=33554432` automatically.
