<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop Device Plugins — Manus

This folder provides a Linux-only example of using the Manus SDK for hand tracking within the Isaac Teleop framework.

## Components

- **Core Library** (`manus_plugin_core`): Interfaces with the Manus SDK (`libIsaacTeleopPluginsManus.so`).
- **Plugin Executable** (`manus_hand_plugin`): The main plugin executable that integrates with the Teleop system.
- **CLI Tool** (`manus_hand_tracker_printer`): A standalone tool to print tracked joint data for verification.

## Prerequisites

- **Linux** (x86_64 tested on Ubuntu 22.04/24.04)
- **Manus SDK** for Linux (automatically downloaded by install script)
- **System dependencies**: The install script will prompt to install required packages

## Installation

### Automated Installation (Recommended)

Use the provided installation script which handles SDK download, dependency installation, and building:

```bash
cd src/plugins/manus
./install_manus.sh
```

The script will:
1. Ask whether to install MANUS Core Integrated dependencies only (faster) or both Integrated and Remote dependencies (includes gRPC, takes longer)
2. Install required system packages
3. Automatically download the MANUS SDK v3.1.1
4. Extract and configure the SDK in the correct location
5. Build the plugin from the TeleopCore root

### Manual Installation

If you prefer to install manually:

1. Obtain a MANUS account and credentials
2. Download the MANUS Core SDK from [MANUS Downloads](https://docs.manus-meta.com/3.1.0/Resources/)
3. Extract and place the `ManusSDK` folder inside `src/plugins/manus/`, or set the `MANUS_SDK_ROOT` environment variable to your installation path

Expected layout:
```text
src/plugins/manus/
  app/
    main.cpp
  core/
    manus_hand_tracking_plugin.cpp
  inc/
    core/
      manus_hand_tracking_plugin.hpp
  tools/
    manus_hand_tracker_printer.cpp
  ManusSDK/        <-- Placed here
    include/
    lib/
```

4. Build from the TeleopCore root:

```bash
cd ../../..  # Navigate to TeleopCore root
cmake -S . -B build
cmake --build build -j
cmake --install build
```

## Running the Plugin

### 1. Setup CloudXR Environment
Before running the plugin, ensure CloudXR environment is configured:

```bash
cd /path/to/TeleopCore
source scripts/setup_cloudxr_env.sh
./scripts/run_cloudxr.sh  # Start CloudXR runtime if not already running
```

### 2. Verify with CLI Tool
Ensure Manus Core is running and gloves are connected.
Run the printer tool to verify data reception:

```bash
./build/bin/manus_hand_tracker_printer
```

### 3. Run the Plugin
The plugin is installed to the `install` directory:

```bash
./install/plugins/manus/manus_hand_plugin
```

## Troubleshooting

- **SDK download fails**: Check your internet connection and try running the install script again
- **Manus SDK not found at build time**: If using manual installation, ensure `ManusSDK` is in `src/plugins/manus/` or `MANUS_SDK_ROOT` is set correctly
- **Manus SDK not found at runtime**: The CMake build configures RPATH to find the SDK libraries. If you moved the SDK, you may need to set `LD_LIBRARY_PATH`
- **No data available**: Ensure Manus Core is running and gloves are properly connected and calibrated
- **CloudXR runtime errors**: Make sure you've sourced `scripts/setup_cloudxr_env.sh` before running the plugin
- **Permission denied for USB devices**: The install script configures udev rules. You may need to run:
  ```bash
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  ```
  Then reconnect your Manus devices.

## License

Source files are under their stated licenses. The Manus SDK is proprietary to Manus and is subject to its own license; it is not redistributed by this project.
