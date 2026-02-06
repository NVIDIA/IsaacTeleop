<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop - Core

Core implementations for Isaac Teleop.

## Structure

```
src/core/
├── oxr/              OpenXR session management
├── deviceio/             OpenXR tracking API (hand, head tracking)
├── devices/          Device interface (future)
├── retargeters/      Retargeter interface (future)
└── python/           Python package configuration
```

## OpenXR Tracking API

Location: `deviceio/`

Provides modular tracking with:
- HandTracker - 26 joints per hand
- HeadTracker - HMD pose
- Extensible for controllers, eyes, etc.

Location: `oxr/`

Provides OpenXR session management:
- OpenXRSession - Headless session creation
- OpenXRSessionHandles - Session handle wrapper

**Quick start:**
```bash
# From IsaacTeleop root
cmake -B build
cmake --build build
cmake --install build

# Run examples
cd install/examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
```

## Development

The project uses CMake for building. See the top-level `BUILD.md` for complete build instructions.

