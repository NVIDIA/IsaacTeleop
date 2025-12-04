<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# OpenXR C++ Examples

C++ examples demonstrating the OpenXR tracking API using the static library.

## Prerequisites

Build the project from the root directory:
```bash
cd ../../..
cmake -B build
cmake --build build
```

This builds:
- The C++ static libraries (OXR and XRIO modules)
- All C++ examples

## Available Examples

### oxr_session_sharing

Demonstrates session sharing between multiple XrioSession instances. This example shows how multiple tracking components can share a single OpenXR session.

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

## Building Standalone

You can also build examples separately if the library is already built:

```bash
mkdir -p build && cd build
cmake .. -DBUILD_EXAMPLES=ON
cmake --build .
```

## Library Linkage

Examples link against the static libraries which include:
- XrioSession - Main session management
- OpenXRSession - Session handling
- HandTracker - Hand tracking functionality
- HeadTracker - Head tracking functionality

All dependencies (including OpenXR) are automatically linked through CMake's target-based approach.

## Adding Your Own Example

To add a new C++ example:

1. Create your `.cpp` file in this directory
2. Edit `CMakeLists.txt`:

```cmake
add_executable(my_example
    my_example.cpp
)

target_link_libraries(my_example
    PRIVATE
        xrio_tracking::xrio_tracking_core
        oxr_session::oxr_session_core
)

install(TARGETS my_example
    RUNTIME DESTINATION examples/oxr/cpp
)
```

3. Rebuild:
```bash
cd ../../../build
cmake --build .
```

## Troubleshooting

### Can't find OpenXR
Ensure OpenXR SDK is installed:
```bash
# Ubuntu/Debian
sudo apt-get install libopenxr-dev

# Or set CMAKE_PREFIX_PATH
export CMAKE_PREFIX_PATH=/path/to/openxr:$CMAKE_PREFIX_PATH
```

### Library not found when running
Make sure you've built from the project root:
```bash
cd ../../..
cmake -B build
cmake --build build
```

