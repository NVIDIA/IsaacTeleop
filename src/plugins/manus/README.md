<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop Device Plugins — Manus

This folder provides a Linux-only example of using the Manus SDK for hand tracking within the TeleopCore framework.

## Components

- **Core Library** (`manus_plugin_core`): Interfaces with the Manus SDK (`libIsaacTeleopPluginsManus.so`).
- **Plugin Executable** (`manus_hand_plugin`): The main plugin executable that integrates with the Teleop system.
- **CLI Tool** (`manus_hand_tracker_printer`): A standalone tool to print tracked joint data for verification.

## Prerequisites

- **Linux** (x86_64, tested on Ubuntu 22.04)
- **Manus SDK** for Linux x86_64

## Getting the Manus SDK

The Manus SDK must be downloaded separately due to licensing.

1. Obtain a Manus account and credentials.
2. Download the MANUS Core SDK from [Manus Downloads](https://my.manus-meta.com/resources/downloads).
3. Extract and place the `ManusSDK` folder inside `src/plugins/manus/`, or set the `MANUS_SDK_ROOT` environment variable to your installation path.

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

## Build

This plugin is built as part of the TeleopCore project. It will be automatically included if the Manus SDK is found.

Run the project build from the repository root:

```bash
cmake -S . -B build
cmake --build build -j
```

If the SDK is not found, the build will skip the Manus plugin with a warning.

## Running the Example

### 1. Verify with CLI Tool
Ensure Manus Core is running and gloves are connected.
Run the printer tool to verify data reception:

```bash
./build/bin/manus_hand_tracker_printer
```

### 2. Run the Plugin
The plugin is installed to the `install` directory.

```bash
./install/plugins/manus/manus_hand_plugin
```

## Troubleshooting

- **Manus SDK not found at build time**: Ensure `ManusSDK` is in `src/plugins/manus/` or `MANUS_SDK_ROOT` is set correctly.
- **Manus SDK not found at runtime**: The build configures RPATH to find the SDK libraries. If you moved the SDK or built without RPATH support, you may need to set `LD_LIBRARY_PATH`.
- **No data available**: Ensure Manus Core is running and gloves are properly connected and calibrated.

## License

Source files are under their stated licenses. The Manus SDK is proprietary to Manus and is subject to its own license; it is not redistributed by this project.
