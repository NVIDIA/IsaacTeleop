<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# TeleopSessionManager Examples

Example demonstrating the TeleopSession API with velocity tracking.

## Example

### Velocity Tracker (`teleop_session_example.py`)

Demonstrates computing velocity from hand and controller movements:
- Tracks hand wrist positions and controller positions
- Computes velocity from position changes
- Uses synthetic hands plugin
- Shows TeleopSession usage with `session.step()`

**Usage:**
```bash
python teleop_session_example.py
```

## Quick Start

```bash
# Build & Install
cd IsaacTeleop
cmake -B build && cmake --build build --target install -j16

# Run example
cd install/examples/teleop_session_manager/python
uv run teleop_session_example.py
```

## See Also

- **Module docs:** `src/core/teleop_session_manager/README.md`
- **Retargeting engine:** `src/core/retargeting_engine/`
