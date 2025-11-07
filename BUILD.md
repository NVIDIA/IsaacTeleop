# Building TeleopCore

This document describes how to build the entire TeleopCore project including libraries and examples.

## Prerequisites

- CMake 3.20 or higher
- C++17 compatible compiler
- OpenXR SDK
- Python 3.10 (for Python bindings)
- uv (for Python dependency management)
- Git (for submodules)

### Initial Setup

After cloning the repository, initialize the git submodules:

```bash
git submodule update --init --recursive
```

Install uv if not already installed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick Start

Build everything with CMake (from project root):

```bash
# Initialize submodules (first time only)
git submodule update --init --recursive

# Build
cmake -B build
cmake --build build
cmake --install build
```

This will:
1. Build the C++ static libraries (OXR and XRIO modules)
2. Build the Python wheels
3. Build the C++ examples
4. Install everything to `./install`

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
│   ├── xrio/               # OpenXR tracking library
│   │   ├── CMakeLists.txt
│   │   ├── cpp/            # C++ library source
│   │   │   └── CMakeLists.txt
│   │   └── python/         # Python bindings for XRIO
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

- The library exports targets for both OXR and XRIO modules
- Include directories are automatically propagated
- Works with both installed and build-tree configurations
- Package config files are generated for easy integration

### Using in Your Project

If you've installed TeleopCore, you can use it in your own CMake project by linking against the appropriate targets.

## Troubleshooting

### CMake can't find OpenXR
Make sure OpenXR SDK is installed and visible to CMake. You may need to set:
```bash
export CMAKE_PREFIX_PATH=/path/to/openxr/install
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

