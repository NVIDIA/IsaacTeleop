<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Third-Party Dependencies

This directory manages third-party dependencies using CMake FetchContent.

## Build Configuration

The `CMakeLists.txt` in this directory handles fetching and building all third-party dependencies:
- **OpenXR SDK**: Automatically fetched and built as a static library
- **yaml-cpp**: YAML parsing library automatically fetched and built as a static library
- **pybind11**: Header-only library, fetched only when `BUILD_PYTHON_BINDINGS=ON`
  - Provides `pybind11::module` target to Python binding modules

Dependencies are downloaded during CMake configuration. No manual initialization is required.

## Current Dependencies

### OpenXR SDK
- **Purpose**: OpenXR loader and headers for XR runtime interaction
- **License**: Apache 2.0
- **Repository**: https://github.com/KhronosGroup/OpenXR-SDK
- **Version**: 75c53b6e853dc12c7b3c771edc9c9c841b15faaa (release-1.1.53)
- **Build**: Static library (to avoid runtime dependencies)

### yaml-cpp
- **Purpose**: YAML parsing for plugin configuration files
- **License**: MIT
- **Repository**: https://github.com/jbeder/yaml-cpp
- **Version**: f7320141120f720aecc4c32be25586e7da9eb978 (0.8.0)
- **Build**: Static library (to avoid runtime dependencies)

### pybind11
- **Purpose**: Python bindings for C++ OpenXR tracking library
- **License**: BSD-style
- **Repository**: https://github.com/pybind/pybind11
- **Version**: a2e59f0e7065404b44dfe92a28aca47ba1378dc4 (v2.11.0-182)
- **Build**: Header-only library

## Adding New Dependencies

To add a new third-party dependency:

1. Update `CMakeLists.txt` in this directory to add a FetchContent declaration:
   ```cmake
   FetchContent_Declare(
       <name>
       GIT_REPOSITORY <repository-url>
       GIT_TAG        <commit-sha-or-tag>
   )
   FetchContent_MakeAvailable(<name>)
   ```

2. Document it in this README with purpose, license, version, and repository information

3. If you need to preserve a specific version, use the full commit SHA in GIT_TAG
