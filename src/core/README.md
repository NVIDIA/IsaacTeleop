# TeleopCore - Core

Core implementations for Isaac Teleop.

## Structure

```
src/core/
├── oxr/              OpenXR session management
├── xrio/             OpenXR tracking API (hand, head tracking)
├── devices/          Device interface (future)
├── retargeters/      Retargeter interface (future)
└── python/           Python package configuration
```

## OpenXR Tracking API

Location: `xrio/`

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
# From TeleopCore root
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

