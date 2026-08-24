---
description: >
  Read-only orientation for an agent about to add or modify a device in IsaacTeleop.
  Covers what the system is, the data/logic flow for a device (with file and symbol
  pointers), and what to read before touching code. Read before Phase 1 or Phase 2.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# IsaacTeleop Codebase & Plugins Context - Phase 0

## What is IsaacTeleop

NVIDIA's C++/Python teleoperation framework. Captures motion from XR headsets, gloves,
and other input devices; retargets it onto robot joint commands via a composable Python
pipeline; optionally records everything to MCAP for offline replay.

**Architecture:** `input hardware → C++ tracker layer → Python retargeting graph → robot commands`

## Device data flow

Seven layers in fixed order. Each node's files and symbols are listed in
`../examples/device.spec.template.yaml`.

```
acquire (plugin) → schema (FlatBuffers) → tracker (C++) → bindings (Python)
→ source (converter) → boundary (tensor shape) → robot step (retargeter)
```

**Plugin** — a standalone process that reads the device (USB, serial, SDK) and pushes or
injects data into CloudXR. No dependency on the main teleop stack. Reference:
`src/plugins/generic_3axis_pedal/` (push), `src/plugins/controller_synthetic_hands/` (inject).

**Schema** — FlatBuffers IDL in `src/core/schema/fbs/`. Check existing schemas before
creating a new one: `hand.fbs`, `joint_state.fbs`, `pedals.fbs`, `controller.fbs`, etc.

**Tracker** — C++ API handle. Live impl reads from OpenXR/plugin; replay impl reads MCAP.
Both factories (`live_deviceio_factory.cpp`, `replay_deviceio_factory.cpp`) need a dispatch row.

**Source** — stateless Python converter (`IDeviceIOSource`). Must be reachable from an
`OutputCombiner` output or it is silently ignored.


## Files to read before adding a device

1. `IsaacTeleop/AGENTS.md` — preflight: CMake rules, DCO sign-off, pre-commit
2. `IsaacTeleop/src/core/AGENTS.md` — source-node discovery footgun; async notes
3. `IsaacTeleop/cmake/cmake-structure.md` — include layout, target naming
4. `IsaacTeleop/docs/source/device/add_device.rst` — official 4-step walkthrough
5. `src/core/schema/fbs/<closest>.fbs` — schema template
6. `src/core/deviceio_trackers/cpp/inc/deviceio_trackers/generic_3axis_pedal_tracker.hpp` — tracker template
7. `src/core/live_trackers/cpp/live_generic_3axis_pedal_tracker_impl.{hpp,cpp}` — live impl pattern
8. `src/python/isaacteleop/retargeting_engine/deviceio_source_nodes/hands_source.py` — source node pattern
9. `src/core/live_trackers/cpp/live_deviceio_factory.cpp` — dispatch table to extend
10. `src/python/isaacteleop/retargeters/SO101/gripper_retargeter.py` — simple retargeter example

## Live visualization (useful for stage 3 verification)

Before writing code, confirm the native headset data is flowing:

- `examples/deviceio_live_view/python/live_deviceio.py` — viser 3-D view of hands, head, controllers, full body
- `examples/mcap_record_replay/python/live_hand.py` — record/replay hands live

Both need a live CloudXR session (`NV_DEVICE_PROFILE=Quest3` for headless).

## Output / feedback devices

**Not yet tested.** No output device has been built or benchmarked with this skill — the sink
path below is documented from the codebase, not verified end to end. Phases 1–2 cover the input
path only; expect gaps if you take this route.

Output devices follow a sink path (no source node needed):

- Tracker: `HapticCommandReaderTracker`
- Sink: subclasses `IDeviceIOSink`, registered via `TeleopSessionConfig(sinks=[...])`
- Plugin: writes commands to hardware after `flush()`
