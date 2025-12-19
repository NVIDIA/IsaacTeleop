<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Building TeleopCore

This document describes how to build the entire TeleopCore project including libraries and examples.

## Prerequisites

- CMake 3.20 or higher
- C++17 compatible compiler
- Python 3.11 (for Python bindings - version configured in root `CMakeLists.txt`)
- uv (for Python dependency management)
- Internet connection (for downloading dependencies via CMake FetchContent)

### Formatting enforcement

On Linux (Ubuntu) builds, clang-format is enforced by default and the build fails if formatting changes would be applied. Install clang-format first:

```bash
sudo apt update
sudo apt install -y clang-format
```

You can disable enforcement if needed:

```bash
cmake -B build -DENABLE_CLANG_FORMAT_CHECK=OFF
```

Useful targets:
- `clang_format_check`: verifies formatting (part of `ALL` on Linux)
- `clang_format_fix`: applies formatting in place

> **Note:** The Python version requirement is centrally configured in the root `CMakeLists.txt` file. 
> To change the Python version, modify the `TELEOPCORE_PYTHON_VERSION` variable in that file.

> **Note:** Dependencies (OpenXR SDK, pybind11, yaml-cpp) are automatically downloaded during CMake configuration using FetchContent. No manual dependency installation or git submodule initialization is required.

### Initial Setup

Install uv if not already installed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick Start

Build everything with CMake (from project root):

```bash
# Build - dependencies are automatically fetched
cmake -B build
cmake --build build
cmake --install build
```

This will:
1. Automatically fetch dependencies (OpenXR SDK, pybind11, yaml-cpp) using CMake FetchContent
2. Build the C++ static libraries (OXR and DEVICEIO modules)
3. Build the Python wheels
4. Build the C++ examples
5. Install everything to `./install`

All options have sensible defaults:
- Build type: `Release`
- Install prefix: `./install`
- Examples: `ON`
- Python bindings: `ON`

## Build Options

### CMake Options

- `CMAKE_BUILD_TYPE`: `Release` or `Debug` (default: `Release`)
- `BUILD_EXAMPLES`: `ON` or `OFF` (default: `ON`)
- `BUILD_PYTHON_BINDINGS`: `ON` or `OFF` (default: `ON`)
- `CMAKE_INSTALL_PREFIX`: Installation directory (default: `install`)

### Examples

Debug build:
```bash
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
```

Build without examples:
```bash
cmake -B build -DBUILD_EXAMPLES=OFF
cmake --build build
```

Build without Python bindings:
```bash
cmake -B build -DBUILD_PYTHON_BINDINGS=OFF
cmake --build build
```

Build with different Python version:
```bash
cmake -B build -DTELEOPCORE_PYTHON_VERSION=3.12
cmake --build build
```

Install to custom location:
```bash
cmake -B build -DCMAKE_INSTALL_PREFIX=/custom/path
cmake --build build
cmake --install build
```

Clean rebuild:
```bash
rm -rf build
cmake -B build
cmake --build build
```

## Project Structure

```
TeleopCore/
├── CMakeLists.txt          # Top-level build file
├── src/core/
│   ├── CMakeLists.txt      # Core build configuration
│   ├── oxr/                # OpenXR session management
│   │   ├── CMakeLists.txt
│   │   ├── cpp/            # C++ session management
│   │   │   └── CMakeLists.txt
│   │   └── python/         # Python bindings for OXR
│   │       └── CMakeLists.txt
│   ├── deviceio/               # OpenXR tracking library
│   │   ├── CMakeLists.txt
│   │   ├── cpp/            # C++ library source
│   │   │   └── CMakeLists.txt
│   │   └── python/         # Python bindings for DEVICEIO
│   │       └── CMakeLists.txt
│   └── python/             # Python package configuration
│       ├── pyproject.toml
│       └── teleopcore_init.py
└── examples/oxr/           # Examples
    ├── CMakeLists.txt      # Examples build configuration
    ├── cpp/                # C++ examples
    │   ├── CMakeLists.txt
    │   └── *.cpp
    └── python/             # Python examples (use uv)
        ├── pyproject.toml
        └── *.py
```

## CMake Integration

The project uses modern CMake target-based approach:

- The library exports targets for both OXR and DEVICEIO modules
- Include directories are automatically propagated
- Works with both installed and build-tree configurations
- Package config files are generated for easy integration

### Using in Your Project

If you've installed TeleopCore, you can use it in your own CMake project by linking against the appropriate targets.

## Troubleshooting

### Dependencies fail to download
If CMake FetchContent fails to download dependencies, check your internet connection. The build requires:
- OpenXR SDK from https://github.com/KhronosGroup/OpenXR-SDK.git
- pybind11 from https://github.com/pybind/pybind11.git
- yaml-cpp from https://github.com/jbeder/yaml-cpp.git

You can also check the `_deps` directory in your build folder for download logs.

### CMake can't find OpenXR
OpenXR SDK is automatically fetched by CMake. If you see errors about missing OpenXR, try cleaning your build directory:
```bash
rm -rf build
cmake -B build
```

### Examples can't find the library
When building from the top-level, examples automatically find the library in the build tree.

## Output

After a successful build:
- **C++ Static Libraries**: Built in `build/src/core/`
- **Python Wheels**: `build/wheels/teleopcore-*.whl`
- **C++ Examples**: `build/examples/oxr/cpp/`
- **Installed files**: `install/`
  - Libraries: `install/lib/`
  - Headers: `install/include/`
  - Python wheels: `install/wheels/`
  - C++ examples: `install/examples/oxr/cpp/`
  - Python examples: `install/examples/oxr/python/`

## Using the Python Wheel

The Python wheel can be installed using `uv` or `pip`:

```bash
# Install from build directory
uv pip install build/wheels/teleopcore-*.whl

# Or with pip
pip install build/wheels/teleopcore-*.whl
```

## Running Examples

### C++ Examples

```bash
# Run from build directory
export XR_RUNTIME_JSON=/path/to/openxr_runtime.json
./build/examples/oxr/cpp/oxr_session_sharing

# Or from install directory
./install/examples/oxr/cpp/oxr_session_sharing
```

### Python Examples

Python examples use `uv` to automatically find and install the built wheel:

```bash
# From install directory (recommended after cmake --install)
cd install/examples/oxr/python
uv run test_modular.py

# Or from source directory (requires build to have completed)
cd examples/oxr/python
uv run test_modular.py
```

Available examples:
- `modular_example.py` - Basic hand + head tracking
- `test_modular.py` - Complete API test
- `test_extensions.py` - Extension query demonstration
- `test_session_sharing.py` - Session sharing between managers

