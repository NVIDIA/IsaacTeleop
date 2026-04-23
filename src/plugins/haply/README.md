<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop Device Plugins — Haply

This folder provides a Linux-only plugin for using the Haply Inverse3 haptic device and VerseGrip controller for hand tracking within the Isaac Teleop framework.

## Components

- **Core Library** (`haply_plugin_core`): Connects to the Haply SDK service via WebSocket and injects hand data into the OpenXR pipeline (`libIsaacTeleopPluginsHaply.so`).
- **Plugin Executable** (`haply_hand_plugin`): The main plugin executable that integrates with the Teleop system.
- **CLI Tool** (`haply_hand_tracker_printer`): A standalone debugging tool that connects directly to the Haply SDK WebSocket and prints raw device state. Does not require OpenXR.

## Prerequisites

- **Linux** (x86_64, tested on Ubuntu 22.04)
- **Haply SDK** runtime service running on localhost (or a reachable host)
- **Haply Inverse3** haptic device connected
- **VerseGrip** controller paired (optional — provides orientation and buttons)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HAPLY_WEBSOCKET_HOST` | `127.0.0.1` | Hostname or IP of the Haply SDK WebSocket service |
| `HAPLY_WEBSOCKET_PORT` | `10001` | Port of the Haply SDK WebSocket service |

## Build

This plugin is built as part of the Isaac Teleop project. No external SDK files are needed at build time — the plugin connects to the Haply SDK service at runtime via WebSocket.

Run the project build from the repository root:

```bash
cmake -S . -B build
cmake --build build -j
```

## Running

### 1. Start the Haply SDK Service

Ensure the Haply SDK runtime service is running and the Inverse3 + VerseGrip hardware is connected. The service should be listening on the configured WebSocket host and port.

### 2. Verify with CLI Tool

Use the standalone printer tool to confirm data reception before starting the full plugin:

```bash
./build/bin/haply_hand_tracker_printer
```

You should see position, velocity, orientation, and button data printed to the terminal. Press `Ctrl+C` to stop.

### 3. Run the Plugin

```bash
./install/plugins/haply/haply_hand_plugin
```

The plugin will:
1. Connect to the Haply SDK WebSocket service
2. Initialize an OpenXR session
3. Map Inverse3 cursor position and VerseGrip orientation to an OpenXR hand
4. Push hand joint data at 90 Hz

## How It Works

The Haply Inverse3 provides a 3-DOF cursor position in space. The VerseGrip adds orientation and button inputs. The plugin maps this data to an OpenXR hand model:

- **Wrist / Palm**: Positioned at the Inverse3 cursor position with VerseGrip orientation
- **Finger joints**: Synthesized at the wrist position (valid but not individually tracked)
- **Root tracking**: If an OpenXR controller is active, its aim pose is used as the root coordinate frame

## Troubleshooting

- **Connection failed**: Ensure the Haply SDK service is running and reachable at the configured host/port. Check `HAPLY_WEBSOCKET_HOST` and `HAPLY_WEBSOCKET_PORT`.
- **No data appearing**: Verify the Inverse3 is powered on and connected. Use `haply_hand_tracker_printer` to test independently of OpenXR.
- **Reconnection**: The plugin automatically reconnects with exponential backoff if the WebSocket connection is lost.

## License

Source files are under the Apache-2.0 license. The Haply SDK service is a separate component not distributed by this project.
