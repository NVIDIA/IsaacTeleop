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
│   ├── CMakeLists.txt       # Third-party dependencies build configuration (uses FetchContent)
│   └── README.md            # Third-party dependencies documentation
└── cloudxr/                 # CloudXR related files
```

## How It Works

The `deps/third_party/CMakeLists.txt` centrally manages all third-party dependencies using CMake FetchContent:

1. **OpenXR SDK**: Automatically fetched and built as a static library
2. **yaml-cpp**: Automatically fetched and built as a static library
3. **pybind11**: Fetched only when `BUILD_PYTHON_BINDINGS=ON` (header-only)
   - Makes `pybind11::module` target available to all Python binding modules

Dependencies are automatically downloaded during CMake configuration. No manual initialization is required.

This centralized approach prevents duplicate includes and ensures consistent configuration across all modules.

## Third-Party Dependencies

### OpenXR SDK
- **Source**: https://github.com/KhronosGroup/OpenXR-SDK.git
- **Version**: 75c53b6e853dc12c7b3c771edc9c9c841b15faaa (release-1.1.53)
- **Purpose**: OpenXR loader and headers for XR runtime interaction
- **Build**: Static library to avoid runtime dependencies
- **License**: Apache 2.0

### yaml-cpp
- **Source**: https://github.com/jbeder/yaml-cpp.git
- **Version**: f7320141120f720aecc4c32be25586e7da9eb978 (0.8.0)
- **Purpose**: YAML parsing for plugin configuration files
- **Build**: Static library to avoid runtime dependencies
- **License**: MIT

### pybind11
- **Source**: https://github.com/pybind/pybind11.git
- **Version**: a2e59f0e7065404b44dfe92a28aca47ba1378dc4 (v2.11.0-182)
- **Purpose**: C++/Python bindings for TeleopCore Python API
- **Build**: Header-only library
- **License**: BSD-style

## Adding New Dependencies

When adding new third-party dependencies:

1. Update `third_party/CMakeLists.txt` to add a FetchContent declaration with the repository URL and specific commit/tag
2. Document it in this README with source, version, purpose, and license
3. Update the main `BUILD.md` with any new requirements

