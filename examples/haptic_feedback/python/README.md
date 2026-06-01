<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Haptic Feedback Examples

End-to-end CLI demos for the tactile / haptic-feedback flow introduced in Isaac
Teleop. Each demo builds a `TeleopSession` with a device-output **sink**: a
tactile-shaped signal feeds a per-device retargeter and a `HapticSink`
(`IDeviceIOSink`), registered via `TeleopSessionConfig(sinks=[...])`. The
session runs the sink each frame and then flushes it to the matching
`IHapticDevice` adapter and out to hardware.

| Example | Input | Device | What it demonstrates |
| --- | --- | --- | --- |
| `controller_haptic_example.py` | Controller trigger value | Motion controller | The first-class device-output sink (`HapticSink` -> `ControllerHapticDevice`) flushed by the session after the graph -- one `ControllerHapticPulse` per endpoint per frame. |

## Motion-controller haptics (`controller_haptic_example.py`)

Pull a controller's trigger and that **same** controller rumbles. This is the
smallest end-to-end wiring of the device-output path: `TriggerToTactile` turns
each trigger value into a `TactileVector`, `TactileVectorToControllerPulse` turns
that into a `ControllerHapticPulse`, and the `HapticSink` drives the controller.
Swap `TriggerToTactile` for any `TactileVector`-producing source (e.g. an Isaac
Lab `ContactSensor` fetch) to rumble from sim contact instead.

### Pipeline

```
ControllersSource (input)
        |
        v
TriggerToTactile  ->  TactileVectorToControllerPulse  ->  HapticSink (IDeviceIOSink)
                                                              |
                                          (after the graph)   v
                                  TeleopSession.flush_to_device(session)
                                      -> ControllerHapticDevice.flush
                                      -> ControllerTracker.apply_haptic_feedback
```

The sink is registered with `TeleopSessionConfig(sinks=[sink_graph])`, not wired
into the returned pipeline. `ControllerHapticDevice` is constructed with
`controllers.get_tracker()`, so `DeviceIOSession` reuses the one
`LiveControllerTrackerImpl` `ControllersSource` already owns and there is no
contention on the underlying controller action set.

### Usage

```bash
uv run controller_haptic_example.py
```

No arguments: pull either trigger to rumble that controller. Press Ctrl+C to exit.

### Notes

- Requires an OpenXR runtime that exposes haptic output on the standard
  `/user/hand/{left,right}/output/haptic` paths. Verified runtimes: Quest 2/3
  via CloudXR, Vive Index, Pico 4. Runtimes that omit `xrApplyHapticFeedback`
  silently no-op without tearing the session down.
- The controller haptic adapter (`ControllerHapticDevice`) is the in-process
  reference for an `IHapticDevice`: `apply(endpoint, values)` stores the value
  inside the graph
  and `flush(session)` writes it after the graph, with the session in scope. See
  the design doc (`IsaacLab/docs/tactile_haptic_feedback_design.md`) for the
  architectural rationale and the cross-process (push-tensor) archetype.

## Quick start

```bash
# Build & install Isaac Teleop (from the repo root). Set CMAKE_INSTALL_PREFIX
# to a writable path so the demo and its install tree end up somewhere you
# can run them from -- the default `/usr/local` requires root and is harder
# to clean up.
cd IsaacTeleop
cmake -B build -DCMAKE_INSTALL_PREFIX="$PWD/install"
cmake --build build --target install -j16

# Run the demo from the install tree.
cd install/examples/haptic_feedback/python
uv run controller_haptic_example.py
```

## See also

- **Design doc:** `IsaacLab/docs/tactile_haptic_feedback_design.md`
- **Haptic adapters:** `isaacteleop.haptic_devices`
- **Per-device mappers:** `isaacteleop.retargeters.tactile_retargeters`
- **Sink:** `isaacteleop.retargeting_engine.deviceio_source_nodes.HapticSink`
