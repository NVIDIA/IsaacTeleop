<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Controller SE3 Tracker Plugin

Example producer for the generic SE3 tracker device type: reads an XR controller's **grip
pose** each tick and republishes it as `Se3TrackerPose` via OpenXR (`SchemaPusher`), in the
OpenXR session base reference space. Pair with an `Se3Tracker` created with the same
`collection_id`.

## Usage

```bash
./controller_se3_tracker_plugin [hand] [collection_id]
```

- **hand**: `left` or `right`. Default `right`.
- **collection_id**: Default `se3_tracker`. This default deliberately matches
  `Se3Tracker::TENSOR_IDENTIFIER` (and `Se3Tracker`'s usual collection id) rather than the
  plugin name, so plugin and tracker rendezvous out of the box. Run multiple instances with
  distinct collection ids for multiple simultaneous trackers.

## Behavior

- Pushes at 90 Hz, **every** tick: when the controller is absent or its grip pose is
  invalid, it pushes `is_valid=false` with an identity filler pose (consumers must gate on
  `is_valid`, never on pose values — see `se3_tracker.fbs`).
- Producer-only: it never registers an `Se3Tracker` in its own OpenXR session.
