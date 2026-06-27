<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
Adapted by X. Tian JP Tech. Initiatives Inc for Foottroller
-->

# Foottroller Plugin

Reads a axes 0-5 and buttons 0-3 from `/dev/input/js*` and pushes `FoottrollerOutput` via OpenXR. Use with `FoottrollerTracker` or `foottroller_printer` with the same `collection_id`.

## Usage

```bash
./foottroller_plugin [device_path] [collection_id]
```

- **device_path**: Default `/dev/input/js0`.
- **collection_id**: Default `foottroller`. Match this when creating `FoottrollerTracker`.

## Axis mapping

- Axis 0 → `stick_x`, 1 → `stick_y`, 2 → `LF_heading`, 3 → `LF_tilt`, 4 → `RF_heading`, 5 → `RF_tilt` (normalized [-1, 1]).
- Btn 0: TS_A, Btn 1: TS_B, Btn 2: TS_C, Btn 3: TS_D

Linux only.
