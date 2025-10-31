# TeleopCore - Core

Core implementations for Isaac Teleop.

## Structure

```
src/core/
├── oxr/              OpenXR tracking API (hand, head tracking)
├── devices/          Device interface (future)
├── retargeters/      Retargeter interface (future)
└── setup.py          pip install -e . for development
```

## OpenXR Tracking API

Location: `oxr/`

Provides modular tracking with:
- HandTracker - 26 joints per hand
- HeadTracker - HMD pose
- Extensible for controllers, eyes, etc.

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

**Documentation:**
- `oxr/README.md` - Complete API guide
- `oxr/ARCHITECTURE.md` - Design principles

## Development

```bash
# From src/core/
pip install -e .
```

This installs TeleopCore in editable mode for live development.

