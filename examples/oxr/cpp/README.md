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
- The C++ static library (`liboxr_tracking_core.a`)
- All C++ examples

## Available Examples

### oxr_session_sharing

Demonstrates session sharing between multiple OpenXRManager instances. This example shows how multiple tracking components can share a single OpenXR session.

**Build output**: `../../../build/examples/oxr/cpp/oxr_session_sharing`

## Running Examples

After building, run from the project root:

```bash
# Set OpenXR runtime (if needed)
export XR_RUNTIME_JSON=/path/to/your/openxr_runtime.json

# Run the example
./build/examples/oxr/cpp/oxr_session_sharing
```

## Building Standalone

You can also build examples separately if the library is already built:

```bash
mkdir -p build && cd build
cmake .. -DBUILD_EXAMPLES=ON
cmake --build .
```

## Library Linkage

Examples link against the static library `oxr_tracking::oxr_tracking_core` which includes:
- OpenXRManager - Main OpenXR session management
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
        oxr_tracking::oxr_tracking_core
)

install(TARGETS my_example
    RUNTIME DESTINATION bin
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

