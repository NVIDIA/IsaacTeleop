<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

## Isaac Teleop Device Plugins — Manus

This folder provides a simplified Linux-only example of using the Manus SDK for hand tracking. It includes:
- A library that interfaces with the Manus SDK
- A minimal CLI example to print joint data from Manus gloves

### Components
- **Manus plugin**: `IsaacTeleopPluginsManus` (shared library)
- **CLI**: `ManusHandTrackerPrinter` (prints tracked joint data)

All targets use modern CMake and C++17.

## Prerequisites
- **Linux** (x86_64, tested: Ubuntu 22.04)
- **CMake** ≥ 3.22 (Ubuntu 22.04 default is supported)
- **GCC/Clang** with C++20 support
- **Manus SDK** for Linux x86_64 (headers and shared libraries)

Note: This project does not redistribute Manus SDK binaries. Provide your own Manus SDK to build and run the Manus example plugin.

## Getting the Manus SDK

The Manus SDK must be downloaded separately due to licensing.

1. Obtain a Manus account and credentials
2. Download the MANUS Core SDK from `https://my.manus-meta.com/resources/downloads` (tested with 2.5.1)
3. Extract and place `ManusSDK/` under `src/plugins/manus/`, or set `MANUS_SDK_ROOT` to your install

Expected layout when vendored:
```
src/plugins/manus/
  ManusHandTrackingPlugin.cpp
  ManusHandTrackingPlugin.h
  ManusSDK/
    include/           # Manus headers (ManusSDK.h, etc.)
    lib/ or lib64/     # Manus shared libs (libManusSDK.so or libManusSDK_Integrated.so)
```

## Build

Presets are provided:

- Default (RelWithDebInfo):
```bash
cmake --preset linux-manus-default
cmake --build --preset manus-default -j
```
- Debug:
```bash
cmake --preset linux-manus-debug
cmake --build --preset manus-debug -j
```
- Release:
```bash
cmake --preset linux-manus-release
cmake --build --preset manus-release -j
```

Artifacts are placed under your build directory (e.g., `build-manus-default`):
- `bin/ManusHandTrackerPrinter` - CLI tool to print joint data
- `lib/libIsaacTeleopPluginsManus.so` - Manus SDK interface library

## Running the Example
1. Ensure Manus gloves are connected and Manus Core is running
2. Run the printer from the build directory:
```bash
./bin/ManusHandTrackerPrinter
```
3. The program will connect to the gloves and print joint positions and orientations
4. Press Ctrl+C to exit

## Advanced
- Custom Manus SDK location:
```bash
MANUS_SDK_ROOT=/opt/ManusSDK cmake --preset linux-manus-default
cmake --build --preset manus-default -j
```
## Troubleshooting
- **Manus SDK not found at runtime**: Set `LD_LIBRARY_PATH` to your Manus SDK `lib/` directory, or ensure the SDK is in your system library path.
- **CMake cannot locate Manus headers/libs**: Verify `MANUS_SDK_ROOT`, or place `ManusSDK/` under `src/plugins/manus/` as shown above.
- **No data available**: Ensure Manus Core is running and gloves are properly connected and calibrated.

## License
Source files are under their stated licenses. The Manus SDK is proprietary to Manus and is subject to its own license; it is not redistributed by the TeleopCore project.
