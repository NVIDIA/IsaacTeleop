# OpenXR Tracking Examples

Examples demonstrating the modular OpenXR tracking API.

## Prerequisites

1. **Build the core library first:**
   ```bash
   # From project root
   cmake -B build
   cmake --build build
   cmake --install build
   ```
   This will build both the C++ static library and the Python wheel.

2. **For Python examples, install uv:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

## Directory Structure

```
examples/oxr/
├── cpp/                    # C++ examples
│   ├── CMakeLists.txt
│   └── oxr_session_sharing.cpp
└── python/                 # Python examples
    ├── pyproject.toml      # uv configuration
    ├── modular_example.py
    ├── test_modular.py
    ├── test_extensions.py
    └── test_session_sharing.py
```

## Python Examples

Python examples use `uv` for dependency management and execution.

### Running Python Examples

After building and installing, navigate to the installed examples:

```bash
# From install directory (recommended)
cd install/examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
```

Or run from source directory:

```bash
# From source directory (requires build to be complete)
cd examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
```

### Available Python Examples

- **modular_example.py** - Basic hand + head tracking
- **test_modular.py** - Complete API test
- **test_extensions.py** - Extension query demonstration
- **test_session_sharing.py** - Session sharing between managers

## C++ Examples

C++ examples are built with CMake and linked against the static library.

### Building C++ Examples

From the top-level project directory:
```bash
cmake -B build
cmake --build build
cmake --install build
```

### Running C++ Examples

**oxr_session_sharing** - Demonstrates session sharing between multiple OpenXRManager instances

```bash
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json

# From build directory
./build/examples/oxr/cpp/oxr_session_sharing

# Or from install directory
./install/examples/oxr/cpp/oxr_session_sharing
```

## Quick Test

### Python Example
```bash
# From project root
cmake -B build
cmake --build build
cmake --install build

# Run Python example
cd install/examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
```

### C++ Example
```bash
# From project root
cmake -B build
cmake --build build

# Run C++ example
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
./build/examples/oxr/cpp/oxr_session_sharing
```

## Build Outputs

After building:
- **C++ Static Library**: `build/src/core/oxr/cpp/liboxr_tracking_core.a`
- **Python Wheel**: `build/wheels/oxr_tracking-1.0.0-*.whl`
- **C++ Examples**: `build/examples/oxr/cpp/oxr_session_sharing`

## Documentation

See `../../src/core/oxr/` for:
- `README.md` - Complete API reference
- `ARCHITECTURE.md` - Design principles
