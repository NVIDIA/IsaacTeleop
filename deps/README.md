<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# TeleopCore Dependencies

This directory contains all project dependencies, organized by type.

## Structure

```
deps/
├── CMakeLists.txt           # Main dependencies build configuration
├── README.md                # This file
├── third_party/             # Third-party open source dependencies
│   ├── CMakeLists.txt       # Third-party dependencies build configuration
│   ├── openxr-sdk/          # OpenXR SDK (git submodule)
│   ├── pybind11/            # pybind11 for Python bindings (git submodule)
│   └── README.md            # Third-party dependencies documentation
└── cloudxr/                 # CloudXR related files
```

## How It Works

The `deps/third_party/CMakeLists.txt` centrally manages all third-party dependencies:

1. **OpenXR SDK**: Built as a static library for all configurations
2. **pybind11**: Added only when `BUILD_PYTHON_BINDINGS=ON`
   - Always uses the git submodule version (not system-installed) for consistency
   - Makes `pybind11::module` target available to all Python binding modules

This centralized approach prevents duplicate includes and ensures consistent configuration across all modules.

## Third-Party Dependencies

### OpenXR SDK
- **Type**: Git submodule
- **Purpose**: OpenXR loader and headers for XR runtime interaction
- **Build**: Static library to avoid runtime dependencies
- **License**: Apache 2.0

### pybind11
- **Type**: Git submodule  
- **Purpose**: C++/Python bindings for TeleopCore Python API
- **Build**: Header-only library
- **License**: BSD-style

## Initialization

After cloning the repository, initialize submodules:

```bash
git submodule update --init --recursive
```

## Adding New Dependencies

When adding new third-party dependencies:

1. Add as a git submodule in the appropriate directory
2. Update `third_party/CMakeLists.txt` to include the new dependency
3. Document it in this README
4. Update the main `BUILD.md` with any new requirements

