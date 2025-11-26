<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Third-Party Dependencies

This directory contains third-party dependencies managed as git submodules.

## Build Configuration

The `CMakeLists.txt` in this directory handles building all third-party dependencies:
- **OpenXR SDK**: Built as a static library for all configurations
- **yaml-cpp**: YAML parsing library built as a static library
- **pybind11**: Header-only library, added only when `BUILD_PYTHON_BINDINGS=ON`
  - Always uses the submodule version (not system-installed) for consistency
  - Provides `pybind11::module` target to Python binding modules

## Current Dependencies

### OpenXR SDK
- **Purpose**: OpenXR loader and headers for XR runtime interaction
- **License**: Apache 2.0
- **Repository**: https://github.com/KhronosGroup/OpenXR-SDK
- **Build**: Static library (to avoid runtime dependencies)

### yaml-cpp
- **Purpose**: YAML parsing for plugin configuration files
- **License**: MIT
- **Repository**: https://github.com/jbeder/yaml-cpp
- **Build**: Static library (to avoid runtime dependencies)

### pybind11 (v2.13.6)
- **Purpose**: Python bindings for C++ OpenXR tracking library
- **License**: BSD-style
- **Repository**: https://github.com/pybind/pybind11
- **Build**: Header-only library

## Initializing Submodules

When cloning TeleopCore for the first time, initialize all submodules:

```bash
git submodule update --init --recursive
```

## Adding New Dependencies

To add a new third-party dependency:

1. Add as a git submodule:
   ```bash
   git submodule add <repository-url> deps/third_party/<name>
   ```

2. Update `CMakeLists.txt` in this directory to include the new dependency

3. Document it in this README with purpose, license, and repository information
