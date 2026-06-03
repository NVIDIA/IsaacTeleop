<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Motion-controller haptics in Isaac Teleop — mini design doc

## Goal

Drive the haptic actuator on an OpenXR motion controller (Quest 2/3 via
CloudXR, Vive Index, Pico 4, …) from a sim signal, through the existing
Isaac Teleop retargeting pipeline, without coupling the rest of the
pipeline to a particular vendor.

This is the **in-process** reference for the vendor-neutral device-output
abstraction (`IDeviceIOSink`). Out-of-process devices (haptic gloves,
force-feedback exoskeletons) plug into the *same* `IDeviceIOSink` /
`IHapticDevice` contract over a cross-process push-tensor transport; that
archetype lands on top of this one.

## Output as a graph phase, symmetric to input

The retargeting graph + `TeleopSession` model an **input phase** and an
**output phase**, symmetric to each other:

- **Input:** an `IDeviceIOSource` is a graph *leaf* with `get_tracker()` and
  `poll_tracker(session)`. The session polls every source *before* running the
  graph and feeds the results in as inputs.
- **Output:** an `IDeviceIOSink` is a terminal graph node with `get_tracker()`
  and `flush_to_device(session)`. The session runs every registered sink as part
  of the graph and then calls `flush_to_device(session)` *after* the graph, with
  the active session in scope. The device write therefore lands in the **same
  frame** the value was computed, with no added latency.

```
Sim signal (contact magnitude,        Retargeter
trigger value, ...)                    (TactileVectorToControllerPulse,
       |                                TactileHeatmapToControllerPulse, ...)
       v                                       |
+---------------+   ControllerHapticPulse      |
|  (graph leaf  | --[amplitude, frequency_hz,  v
|   source or   |   duration_s]-->   +----------------------------------+
|   external)   |                    |  HapticSink (IDeviceIOSink)      |
+---------------+                    |   _compute_fn: device.apply(     |
                                     |     endpoint, values) (stores)   |
                                     +----------------+-----------------+
                                                      | after the graph,
                                                      | with the session:
                                                      v
                                     +----------------------------------+
                                     |  TeleopSession.flush_to_device   |
                                     |   -> ControllerHapticDevice      |
                                     |        .flush(session)            |
                                     |   -> ControllerTracker            |
                                     |        .apply_haptic_feedback(...) |
                                     +----------------+-----------------+
                                                      v
                                       xrApplyHapticFeedback /
                                       xrStopHapticFeedback
```

## Per-frame data flow

1. A retargeter (e.g. `TactileVectorToControllerPulse`) reduces sim-side
   tactile data into one `ControllerHapticPulse =
   [amplitude, frequency_hz, duration_s]` per endpoint.
2. `HapticSink._compute_fn` calls `device.apply(endpoint, values)` for each
   endpoint present in its inputs this frame. `apply` only *stores* the latest
   value per endpoint — `_compute_fn` has no `XrSession` in scope.
3. After the graph runs, `TeleopSession` calls `sink.flush_to_device(session)`,
   which delegates to `ControllerHapticDevice.flush(session)`. That drains
   the stored pulses and forwards each to `controller_tracker.apply_haptic_feedback(
   session, endpoint, amplitude, frequency_hz, duration_s)`.
4. The pybind shim translates `endpoint` (`"left"`/`"right"`) → `is_left` and
   dispatches to `core::ControllerTracker::apply_haptic_feedback`, which forwards
   to `LiveControllerTrackerImpl::apply_haptic_feedback`.
5. The impl maps:
    - `amplitude == 0` → `xrStopHapticFeedback`
    - `amplitude > 0` → `xrApplyHapticFeedback` with
      `XrHapticVibration{ amplitude, frequency, duration }`. Zero for
      `frequency_hz` / `duration_s` maps to `XR_FREQUENCY_UNSPECIFIED`
      and `XR_MIN_HAPTIC_DURATION` respectively.

## Layered classes

| Layer | Type | Lives in |
|---|---|---|
| Vendor-neutral graph sink | `IDeviceIOSink` (ABC) | `isaacteleop.retargeting_engine.deviceio_source_nodes.sink_interface` |
| Vendor-neutral sink node | `HapticSink` (`IDeviceIOSink`) | `isaacteleop.retargeting_engine.deviceio_source_nodes.haptic_sink` |
| Vendor adapter interface | `IHapticDevice` (ABC) | `isaacteleop.haptic_devices.interface` |
| Device-side schema | `ControllerHapticPulse` (`TensorGroupType`) | `isaacteleop.retargeting_engine.tensor_types.tactile_types` |
| Per-device mappers | `TactileVectorToControllerPulse`, `TactileHeatmapToControllerPulse` | `isaacteleop.retargeters.tactile_retargeters` |
| Controller device adapter | `ControllerHapticDevice` (`IHapticDevice`) | `isaacteleop.haptic_devices.controller` |
| C++ tracker public API | `core::ControllerTracker::apply_haptic_feedback` | `src/core/deviceio_trackers/cpp/controller_tracker.{hpp,cpp}` |
| C++ tracker abstract impl | `core::IControllerTrackerImpl::apply_haptic_feedback` | `src/core/deviceio_base/cpp/inc/deviceio_base/controller_tracker_base.hpp` |
| Live OpenXR impl | `core::LiveControllerTrackerImpl::apply_haptic_feedback` | `src/core/live_trackers/cpp/live_controller_tracker_impl.{hpp,cpp}` |
| Replay impl (no-op) | `core::ReplayControllerTrackerImpl::apply_haptic_feedback` | `src/core/replay_trackers/cpp/replay_controller_tracker_impl.hpp` |
| OpenXR function pointers | `xrApplyHapticFeedback`, `xrStopHapticFeedback` | `src/core/oxr_utils/cpp/inc/oxr_utils/oxr_funcs.hpp` |

## Named endpoints, not hardcoded sides

A device declares the actuators it drives via `IHapticDevice.endpoints()`.
`HapticSink` exposes one optional input port per endpoint. Hand-mounted devices
(controllers, gloves) use `("left", "right")`; a single grounded force device
(e.g. Haply Inverse3) would use `("device",)`; a multi-actuator exoskeleton uses
per-actuator names. The endpoint name is opaque to the graph (and, for
cross-process devices, travels on the wire).

## Why `apply` (store) **and** `flush` (write)?

`xrApplyHapticFeedback(session, …)` needs an `XrSession`. The retargeting graph
executes `BaseRetargeter._compute_fn` outside session context, so the sink
can't make the call directly. The split is:

- **`HapticSink._compute_fn`** (graph node) calls `device.apply(endpoint, values)`,
  which stores the latest value per endpoint.
- **`TeleopSession`** calls `sink.flush_to_device(session)` once per frame after
  the graph, with the active session, which writes to the device.

Coalescing on the device side (*latest wins per endpoint per frame*) is
lossless because `xrApplyHapticFeedback` already supersedes any in-flight pulse
on the same action. Force-feedback paths care about phase, not just amplitude —
they are expected to run their tight control loop in the device's own process
on the latest pushed target, so the per-frame flush cadence is sufficient.

## Why route through `LiveControllerTrackerImpl` and not a new plugin?

OpenXR is already the abstraction the live-tracker layer is built on.
`ControllerTracker` already owns the `XrActionSet` for grip/aim/buttons;
adding an `XR_ACTION_TYPE_VIBRATION_OUTPUT` action to the same set is
one extra binding, not a new plugin. A separate plugin would mean a
second `XrActionSet` on the same session, which collides with OpenXR's
attach-once rule.

## Minimal wiring (one-handed cheat sheet)

```python
from isaacteleop.haptic_devices.controller import ControllerHapticDevice
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource, HapticSink,
)
from isaacteleop.retargeters.tactile_retargeters import TactileVectorToControllerPulse
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

controllers = ControllersSource("controllers")
# Reuse the ControllersSource tracker so DeviceIOSession creates one
# LiveControllerTrackerImpl (one OpenXR action set per session).
device = ControllerHapticDevice(controllers.get_tracker())
sink = HapticSink("haptic_sink", device)
mapper = TactileVectorToControllerPulse("vec_to_pulse", num_taxels=1)

# <sim source> -> mapper -> sink["left"]/sink["right"]
sink_graph = sink.connect({"left": mapper_graph.output(...), "right": ...})

config = TeleopSessionConfig(
    app_name="MyApp",
    pipeline=combiner,        # whatever step() should return
    sinks=[sink_graph],       # the sink runs + flushes each frame
)
```

The one footgun left: **the `ControllerTracker` must be shared** with the
`ControllersSource`. Constructing a new `ControllerTracker()` for the device
spawns a second `LiveControllerTrackerImpl`, and the second
`xrAttachSessionActionSets` call fails with
`XR_ERROR_ACTIONSETS_ALREADY_ATTACHED`. Pass `controllers.get_tracker()`.

## Failure & lifecycle policy

- **Runtime missing `xrApplyHapticFeedback` / `xrStopHapticFeedback`:**
  silent no-op. Function pointers are loaded lazily via
  `xrGetInstanceProcAddr`; the impl null-checks at the call site.
- **OpenXR returns failure:** logged **once per endpoint** behind an atomic
  compare-exchange gate, then silently no-op forever.
- **`IHapticDevice.flush` is non-throwing:** the device swallows hardware
  errors (log-once-and-no-op). Haptics are nice-to-have; a hardware hiccup must
  never tear down a teleop session.
- **Non-finite inputs (NaN / ±Inf)** from upstream: sanitized to safe
  defaults before being cast to `XrDuration` (signed 64-bit ns).
- **Replay sessions:**
  `ReplayControllerTrackerImpl::apply_haptic_feedback` is a no-op — no hardware
  to drive. A standalone-tracker sink whose tracker is not registered in replay
  fails soft via the non-throwing `flush` contract.

## Pointers

- Full design doc: `IsaacLab/docs/tactile_haptic_feedback_design.md`.
- End-to-end example:
  `examples/haptic_feedback/python/controller_haptic_example.py` —
  pull a trigger to rumble that same controller.
- Tests:
    - `src/core/retargeting_engine_tests/python/test_haptic_sink.py` —
      sink dispatch contract, named endpoints, connect-time type check,
      `get_tracker` / `flush_to_device` delegation.
    - `src/core/retargeting_engine_tests/python/test_haptic_devices.py` —
      OpenXR device: store/flush semantics, latest-wins coalescing,
      flush-clears, once-per-endpoint logging.
    - `src/core/teleop_session_manager_tests/python/test_teleop_session.py` —
      `TestOutputSinks`: sink discovery, post-graph flush ordering, and an
      external-input-fed sink.
    - `src/core/retargeting_engine_tests/python/test_tactile_retargeters.py` —
      `ControllerHapticPulse`-shaped mappers and shared gain curve.
