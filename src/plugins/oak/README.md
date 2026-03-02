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
# Record a single color stream
./build/src/plugins/oak/camera_plugin_oak --add-stream=camera=Color,output=./color.h264

# Record multiple streams
./build/src/plugins/oak/camera_plugin_oak \
  --add-stream=camera=Color,output=./color.h264 \
  --add-stream=camera=MonoLeft,output=./left.h264 \
  --add-stream=camera=MonoRight,output=./right.h264

# Record with a live preview window
./build/src/plugins/oak/camera_plugin_oak \
  --add-stream=camera=Color,output=./color.h264 --preview

# Record metadata to MCAP
./build/src/plugins/oak/camera_plugin_oak \
  --add-stream=camera=Color,output=./color.h264 \
  --mcap-filename=./metadata.mcap

# Show help
./build/src/plugins/oak/camera_plugin_oak --help
```

Press `Ctrl+C` to stop recording.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--add-stream=camera=<name>,output=<path>` | (at least one required) | Add a capture stream. `camera` is one of `Color`, `MonoLeft`, `MonoRight`. Repeatable. |
| `--fps=N` | 30 | Frame rate for all streams |
| `--bitrate=N` | 8000000 | H.264 bitrate (bps) |
| `--quality=N` | 80 | H.264 quality (1-100) |
| `--device-id=ID` | first available | OAK device MxId |
| `--preview` | off | Open a live SDL2 window showing the color camera feed |
| `--collection-prefix=PREFIX` | | Push per-frame metadata via OpenXR tensor extensions |
| `--mcap-filename=PATH` | | Record per-frame metadata to an MCAP file |

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

All dependencies are built automatically via CMake:

- **DepthAI** - OAK camera interface
- **SDL2** - Live preview window (used by `--preview`)

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
