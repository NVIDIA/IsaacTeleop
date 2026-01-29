<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# OpenXR C++ Examples

C++ examples demonstrating the OpenXR tracking API

## Available Examples

### oxr_session_sharing

Demonstrates session sharing between multiple DeviceIOSession instances. This example shows how multiple tracking components can share a single OpenXR session.

**Build output**: `../../../build/examples/oxr/cpp/oxr_session_sharing`

### oxr_simple_api_demo

Demonstrates the simple API for OpenXR tracking.

**Build output**: `../../../build/examples/oxr/cpp/oxr_simple_api_demo`

## Running Examples

After building, run from the project root:

```bash
# Set OpenXR runtime (if needed)
export XR_RUNTIME_JSON=/path/to/your/openxr_runtime.json

# Run the examples
./build/examples/oxr/cpp/oxr_session_sharing
./build/examples/oxr/cpp/oxr_simple_api_demo
```

## Library Linkage

Examples link against the static libraries which include:
- DeviceIOSession - Main session management
- OpenXRSession - Session handling
- HandTracker - Hand tracking functionality
- HeadTracker - Head tracking functionality

All dependencies (including OpenXR) are automatically linked through CMake's target-based approach.

## Troubleshooting

### Can't find OpenXR
Ensure OpenXR SDK is installed:
```bash
# Ubuntu/Debian
sudo apt-get install libopenxr-dev

# Or set CMAKE_PREFIX_PATH
export CMAKE_PREFIX_PATH=/path/to/openxr:$CMAKE_PREFIX_PATH
```
