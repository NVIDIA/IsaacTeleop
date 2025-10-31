# Third-Party Dependencies

This directory contains third-party dependencies managed as git submodules.

## Current Dependencies

### pybind11 (v2.13.6)
- **Purpose**: Python bindings for C++ OpenXR tracking library
- **License**: BSD-style
- **Repository**: https://github.com/pybind/pybind11

## Initializing Submodules

When cloning TeleopCore for the first time, initialize all submodules:

```bash
git submodule update --init --recursive
```
