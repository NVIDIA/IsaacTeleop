<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop Camera Streamer

A [Holoscan](https://docs.nvidia.com/holoscan/sdk-user-guide/)-based multi-camera streaming application for [Isaac Teleop](../../README.md). It captures video from cameras on a robot and delivers it to the operator.

The application is configured along two independent axes, **source** and **display**, that can be freely combined:

### Source — how camera frames enter the pipeline

| Mode | Description | Use case |
|---|---|---|
| **Local** | The entire stack runs on the robot itself (Jetson/ARM). | Lowest latency. Direct Robot to XR device connection. |
| **RTP** | A lightweight sender on the robot encodes each stream to H.264 and ships it over UDP. A receiver on the workstation decodes and displays. | Robot-to-workstation streaming over the network. |

### Display — where the operator sees the video

| Mode | Description | Use case |
|---|---|---|
| **Monitor** | Frames are tiled into a 2D desktop window. | Development, debugging, and Teleop without XR. |
| **XR** | Frames are rendered as 3D planes inside a head-mounted display via CloudXR using Holoscan XR operators. | Immersive teleoperation with a head-mounted display. |

The two axes are orthogonal: you can receive cameras over RTP and display in XR, or run the full stack locally on the robot and stream straight to a headset. In XR mode the camera pipeline shares a single CloudXR connection with Isaac Teleop's device tracking, so the operator's input and the robot's camera feeds travel over the same session.

### Features

- **Shared CloudXR runtime**: in XR mode, camera streaming runs inside the same CloudXR session as Isaac Teleop's device. One connection carries both operator input and robot video.
- **Multi-camera, mono & stereo**: configure any number of cameras, each with independent resolution, frame rate, and bitrate.
- **Pluggable camera sources**: swap or add camera operators in the Holoscan pipeline without changing the streaming stack.
- **CloudXR headset streaming**: render camera feeds as positioned 3D planes in a XR headset with per-plane distance, size, offset, and head-relative lock modes.
- **H.264 hardware encoding/decoding**: NVENC on the sender, NVDEC on the receiver.
- **Reusable subgraph**: the receiver/display pipeline is packaged as a Holoscan `Subgraph` that can be embedded in larger applications (e.g., a full teleoperation stack).
- **Stream health monitoring**: per-stream timeouts with automatic "unavailable" placeholders.
- **Docker-based build & deploy**: two-step GPU-aware Docker build, with dev (`shell`) and production (`deploy-sender`) modes. Config changes take effect on restart without rebuilding.
- **Cross-platform**: runs on Jetson (ARM) and x86_64 with architecture-aware base images.

## Quick Start

```bash
# Build the Docker image (two-step: base image + C++ operators with GPU)
./camera_streamer.sh build

# Run the camera app (local cameras, monitor window)
./camera_streamer.sh run -- --source local --mode monitor

# Run the camera app (RTP receiver, XR headset)
./camera_streamer.sh run -- --source rtp --mode xr

# Interactive dev shell (host source mounted, edits reflected immediately)
./camera_streamer.sh shell
python3 teleop_camera_app.py --source local --mode monitor    # inside container
python3 teleop_camera_sender.py --host 192.168.1.100           # inside container

# Deploy the sender on the robot
./camera_streamer.sh deploy-sender --receiver-host 192.168.1.100
```

## Commands

| Command | Description |
|---|---|
| `build [--sender-only]` | Build Docker image (encoder + decoder + XR by default) |
| `shell` | Interactive dev shell (host source mounted) |
| `run [-- ARGS...]` | Run `teleop_camera_app.py` with the given arguments |
| `deploy-sender` | Deploy the RTP sender as a persistent container |
| `list-cameras` | List connected OAK-D and ZED cameras |
| `status` | Show whether the container is running |
| `logs` | Follow container logs |
| `stop` | Stop the container |
| `restart` | Restart the container (picks up config changes) |
| `clean` | Remove Docker images |

## Development & Deployment

### Dev shell (`shell`)

Opens an interactive bash session inside the container with the host `camera_streamer/` directory mounted. Python and config edits on the host are reflected immediately — no rebuild needed. Built C++ libs live at `build/python/` on the host from the build step.

If the container is already running, a second `shell` call attaches to it (`docker exec`).

### Production mode (`deploy-sender`)

Deploys the RTP sender (`teleop_camera_sender.py`) as a persistent container with `--restart unless-stopped`. The config file is bind-mounted so you can edit it on the host and restart without rebuilding.

```bash
./camera_streamer.sh deploy-sender --receiver-host 192.168.1.100
vim config/multi_camera.yaml           # edit config
./camera_streamer.sh restart            # picks up changes
```

## Camera Configuration

Edit a config file under `config/` (e.g. `config/multi_camera.yaml`). Each camera has a name, type, and one or more streams with unique ports and stream IDs. Sample configs:

| Config | Description |
|---|---|
| `config/v4l2.yaml` | Single V4L2 camera (USB/HDMI capture) |
| `config/multi_camera.yaml` | 1 stereo ZED + 2 mono OAK-D (default) |
| `config/single_camera.yaml` | Single mono OAK-D |

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

### Finding Camera Serial Numbers

A utility script is provided to find camera serial numbers (OAK-D and Zed) and v4l2 camera configs.

```bash
./camera_streamer.sh list-cameras
```

## Platform Notes

> **Jetson Orin**: Not supported by the default Dockerfile. Orin uses a different Holoscan base image (`-igpu`) and lacks NVENC, so only OAK-D cameras (VPU encoding) work. To add Orin support, adapt the `BASE_IMG_ARM64` arg, ZED SDK URL, and CuPy package in the Dockerfile.

## Troubleshooting

- **Camera not found**: Check USB connection. Run `list-cameras` to verify detection.
- **No video on receiver**: Check `--receiver-host` IP. Verify firewall allows UDP on configured ports.
