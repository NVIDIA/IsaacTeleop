<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# OAK Camera Plugin

C++ plugin that captures H.264 video from OAK cameras and saves to raw H.264 files.

## Features

- **Hardware H.264 Encoding**: Uses OAK's built-in video encoder
- **Raw H.264 Recording**: Writes H.264 NAL units directly to file (no container overhead)
- **OpenXR Integration**: Optional CloudXR runtime integration
- **Self-contained build**: DepthAI built automatically via CMake

## Build

DepthAI is fetched and built automatically via FetchContent. The first build takes ~10-15 minutes (mostly DepthAI and its Hunter dependencies), subsequent builds are fast.

```bash
cd IsaacTeleop

# Configure and build
cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=ON
cmake --build build --target camera_plugin_oak --parallel
```

## Usage

```bash
# Record to a file (--output is required)
./build/src/plugins/oak/camera_plugin_oak --output=./recordings/session.h264

# Custom path and camera settings
./build/src/plugins/oak/camera_plugin_oak --output=/tmp/session.h264 --width=1920 --height=1080 --fps=30 --bitrate=15000000

# Show help
./build/src/plugins/oak/camera_plugin_oak --help
```

Press `Ctrl+C` to stop recording.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--width` | 1920 | Frame width |
| `--height` | 1080 | Frame height |
| `--fps` | 30 | Frame rate |
| `--bitrate` | 8000000 | H.264 bitrate (bps) |
| `--quality` | 80 | H.264 quality (1-100) |
| `--output` | (required) | Full path for recording file |
| `--collection-prefix` | oak_camera | Tensor collection prefix for metadata (per-stream IDs: `prefix/StreamName`) |

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐     ┌──────────────┐
│   OakCamera     │────>│    FrameSink     │────>│ RawDataWriter │────>│  .h264 File  │
│  (H.264 encode) │     │ (write + push)   │     │ (file writer) │     │              │
└─────────────────┘     └──────┬───────────┘     └───────────────┘     └──────────────┘
     core/                     │    core/                core/
                               v
                     ┌──────────────────┐
                     │ MetadataPusher   │
                     │ (OpenXR tensor)  │
                     └──────────────────┘
```

## Dependencies

**System dependencies** (install before building):

```bash
sudo apt install libusb-1.0-0-dev
```

**Automatically built via CMake:**

- **DepthAI** - OAK camera interface

## Output Format

The plugin writes raw H.264 NAL units (Annex B format) to `.h264` files. To play or convert:

```bash
# Play with ffplay
ffplay -f h264 recording.h264

# Convert to MP4
ffmpeg -f h264 -i recording.h264 -c copy output.mp4

# Convert with specific framerate
ffmpeg -f h264 -framerate 30 -i recording.h264 -c copy output.mp4
```

## Troubleshooting

```bash
# Check OAK camera connection
lsusb | grep 03e7

# Verify recording (convert to MP4 first)
ffmpeg -f h264 -i recording.h264 -c copy recording.mp4
ffprobe recording.mp4

# Check frame count
ffprobe -show_entries stream=nb_frames recording.mp4
```
