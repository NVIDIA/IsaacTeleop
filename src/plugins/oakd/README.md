# OAK-D Camera Plugin

C++ plugin that captures H.264 video from OAK-D cameras and saves to raw H.264 files.

## Features

- **Hardware H.264 Encoding**: Uses OAK-D's built-in video encoder
- **Raw H.264 Recording**: Writes H.264 NAL units directly to file (no container overhead)
- **OpenXR Integration**: Optional CloudXR runtime integration
- **Self-contained build**: DepthAI built automatically via CMake

## Build

DepthAI is built automatically on first build. Initial build takes ~10-15 minutes, subsequent builds are fast.

```bash
cd IsaacTeleop

# Configure
cmake -B build

# Build DepthAI (first time only)
cmake --build build --target depthai_external --parallel

# Reconfigure and build plugin
cmake -B build
cmake --build build --target camera_plugin_oakd --parallel
```

## Usage

```bash
# Record with defaults (auto-named file in ./recordings/)
./build/src/plugins/oakd/camera_plugin_oakd

# Record to specific file
./build/src/plugins/oakd/camera_plugin_oakd --record=my_video.h264

# Custom camera settings
./build/src/plugins/oakd/camera_plugin_oakd --width=1920 --height=1080 --fps=30 --bitrate=15000000

# Show help
./build/src/plugins/oakd/camera_plugin_oakd --help
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
| `--record` | auto | Output file path (.h264) |
| `--record-dir` | ./recordings | Directory for auto-named recordings |
| `--retry-interval` | 5 | Camera init retry interval (seconds) |
| `--plugin-root-id` | oakd_camera | Plugin ID for TeleopCore integration |

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐     ┌──────────────┐
│   OakDCamera    │────>│  CameraPlugin    │────>│ RawDataWriter │────>│  .h264 File  │
│  (H.264 encode) │     │  (lifecycle mgmt)│     │ (file writer) │     │              │
└─────────────────┘     └──────────────────┘     └───────────────┘     └──────────────┘
     oakd/                      core/                   core/
```

## Dependencies

**System dependencies** (install before building):

```bash
sudo apt install libusb-1.0-0-dev
```

**Automatically built via CMake:**

- **DepthAI** - OAK-D camera interface

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
# Check OAK-D camera connection
lsusb | grep 03e7

# Verify recording (convert to MP4 first)
ffmpeg -f h264 -i recording.h264 -c copy recording.mp4
ffprobe recording.mp4

# Check frame count
ffprobe -show_entries stream=nb_frames recording.mp4
```
