# Camera Plugin

C++ plugin that captures H.264 video from cameras and saves directly to MP4 using FFmpeg.

## Features

- **Modular Camera Support**: Currently supports OAK-D (hardware H.264 encoding)
- **Shared Infrastructure**: Reusable MP4 writer and plugin lifecycle management
- **Direct MP4 Recording**: Uses FFmpeg libavformat for robust MP4 muxing
- **Auto-reconnect**: Automatic camera reconnection on disconnect
- **OpenXR Integration**: Optional CloudXR runtime integration
- **Self-contained build**: All dependencies built automatically via CMake

## Structure

```
camera/
├── core/              # Shared: CameraConfig, RecordConfig, Mp4Writer, CameraPlugin
├── oakd/              # OAK-D specific: OakDCamera implementation + main.cpp
└── (future: realsense/, zed/, etc.)
```

## Build

All dependencies (DepthAI and FFmpeg) are built automatically. First build takes ~15-20 minutes, subsequent builds are fast.

```bash
cd IsaacTeleop

# Configure (detects/plans dependencies)
cmake -B build

# Build dependencies (first time only)
cmake --build build --target depthai_external ffmpeg_external --parallel

# Reconfigure to detect built dependencies
cmake -B build

# Build plugin
cmake --build build --target camera_plugin_oakd --parallel
```

Or, if you prefer system FFmpeg (faster initial build):

```bash
# Install system FFmpeg
sudo apt install libavformat-dev libavcodec-dev libavutil-dev

# Build
cmake -B build && cmake --build build --target camera_plugin_oakd --parallel
```

## Usage

```bash
# Record with defaults (auto-named file in ./recordings/)
./build/src/plugins/camera/oakd/camera_plugin

# Record to specific file
./build/src/plugins/camera/oakd/camera_plugin --record=my_video.mp4

# Custom camera settings
./build/src/plugins/camera/oakd/camera_plugin --width=1920 --height=1080 --fps=30 --bitrate=15000000

# Show help
./build/src/plugins/camera/oakd/camera_plugin --help
```

Press `Ctrl+C` to stop recording.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--width` | 1280 | Frame width |
| `--height` | 720 | Frame height |
| `--fps` | 30 | Frame rate |
| `--bitrate` | 8000000 | H.264 bitrate (bps) |
| `--quality` | 80 | H.264 quality (1-100) |
| `--record` | auto | Output file path (.mp4) |
| `--record-dir` | ./recordings | Directory for auto-named recordings |
| `--retry-interval` | 5 | Camera reconnect interval (seconds) |
| `--plugin-root-id` | camera | Plugin ID for TeleopCore integration |

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌──────────────┐
│   OakDCamera    │────>│  CameraPlugin    │────>│  Mp4Writer   │────>│   .mp4 File  │
│  (H.264 encode) │     │  (lifecycle mgmt)│     │  (FFmpeg)    │     │              │
└─────────────────┘     └──────────────────┘     └──────────────┘     └──────────────┘
     oakd/                      core/                   core/
```

## Dependencies

All automatically built via CMake:

- **DepthAI** - OAK-D camera interface
- **FFmpeg** - MP4 muxing (libavformat)

## Troubleshooting

```bash
# Check OAK-D camera connection
lsusb | grep 03e7

# Verify recording
ffprobe recording.mp4

# Check frame count
ffprobe -show_entries stream=nb_frames recording.mp4
```
