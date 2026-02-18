# OAK-D Camera Streamer Example

Low-latency H.264 video streaming from OAK-D camera using DepthAI + GStreamer.

Note: This is a standalone example and not integrated in Isaac Teleop.

## Quick Start

### Deploy to Jetson

```bash
cd examples/cam_streamer

# Deploy with defaults (192.168.123.164, stream to 192.168.123.222:5000)
./cam_streamer.sh deploy

# Custom configuration
./cam_streamer.sh deploy --ip $ROBOT_IP --user $ROBOT_USER --stream-host $RECEIVER_IP
```

Builds arm64 image, deploys to robot via SSH. Container auto-restarts on boot.

### Run Receiver

```bash
./cam_streamer.sh receive --port 5000
```

### Local Testing

Test the full pipeline locally with an OAK-D camera connected to your x86 machine:

```bash
# Terminal 1: start receiver
./cam_streamer.sh receive

# Terminal 2: start sender (streams to localhost by default)
./cam_streamer.sh send

# Or stream to a specific host
./cam_streamer.sh send --stream-host 192.168.1.100 --stream-port 5000
```

## Commands

```bash
./cam_streamer.sh deploy    # Build & deploy sender to Jetson
./cam_streamer.sh send      # Run sender locally (for testing)
./cam_streamer.sh receive   # Run receiver locally
./cam_streamer.sh log       # View remote sender logs
./cam_streamer.sh stop      # Stop remote sender
./cam_streamer.sh restart   # Restart remote sender
```

## Configuration

| Setting | Default | Override |
|---------|---------|----------|
| Robot IP | 192.168.123.164 | `--ip` |
| Robot User | unitree | `--user` |
| Stream Host | 192.168.123.222 | `--stream-host` |
| Stream Port | 5000 | `--stream-port` / `--port` |

## Troubleshooting

```bash
# Check camera connection
ssh unitree@192.168.123.164 'lsusb | grep 03e7'

# View sender logs
./cam_streamer.sh log

# Allow UDP traffic
sudo ufw allow 5000/udp

# Rebuild images (if needed)
./cam_streamer.sh clean
```

## Requirements

**Sender (Jetson/arm64):** Docker, OAK-D camera, network access
**Receiver (x86):** Docker, X11 display, network access
