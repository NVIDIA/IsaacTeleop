<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Haptic Feedback Examples

End-to-end CLI demos for the tactile / haptic-feedback flow introduced in Isaac
Teleop. Each demo builds a `TeleopSession` whose pipeline reaches **backwards**
through the retargeting graph -- from a tactile-shaped signal source, through
the per-device retargeter and `HapticSink`, into the matching
`IHapticDevice` adapter and out to hardware.

| Example | Input | Device | What it demonstrates |
| --- | --- | --- | --- |
| `openxr_controller_haptic_example.py` | Controller trigger value (or a synthetic sine) | OpenXR motion controller | The full session-aware sink + source pattern (`HapticSink` + `OpenXRControllerHapticSource`) -- one `ControllerHapticPulse` per hand per frame. |

## OpenXR motion-controller haptics (`openxr_controller_haptic_example.py`)

Drives the haptic actuator on each OpenXR motion controller through the full
stack. Two demo modes:

| Mode (default `trigger`) | Behaviour |
| --- | --- |
| `--mode trigger` (default; `--same-hand` to flip) | Pulling the **left** trigger rumbles the **right** controller and vice versa (cross-hand by default). |
| `--mode sine` | Both controllers rumble on a smooth half-rectified sine envelope. No controller input required -- useful as a hardware smoke test. |

### Pipeline

```
ControllersSource (input)              OpenXRControllerHapticDevice
        |                                       ^   ^
        v                                       |   |
TriggerToTactile  ->  TactileVectorToControllerPulse  ->  HapticSink
                                                          |
                                                          v
                                          OpenXRControllerHapticSource
                                              poll_tracker(session)
```

The same `ControllerTracker` instance is reused by both `ControllersSource` and
`OpenXRControllerHapticSource`, so `DeviceIOSession` only creates one
`LiveControllerTrackerImpl` and there is no contention on the underlying
OpenXR action set.

### Usage

```bash
# Default: cross-hand trigger -> rumble (most fun on a single user).
uv run openxr_controller_haptic_example.py

# Same-hand instead of cross-hand.
uv run openxr_controller_haptic_example.py --same-hand

# Open-loop sine wave smoke test (no input needed).
uv run openxr_controller_haptic_example.py --mode sine --sine-period 1.5

# Override OpenXR pulse parameters (defaults select runtime-picked values).
uv run openxr_controller_haptic_example.py --frequency-hz 320 --duration-s 0.05
```

### Notes

- Requires an OpenXR runtime that exposes haptic output on the standard
  `/user/hand/{left,right}/output/haptic` paths. Verified runtimes: Quest 2/3
  via CloudXR, Vive Index, Pico 4. Runtimes that omit `xrApplyHapticFeedback`
  silently no-op without tearing the session down.
- `--frequency-hz 0` selects `XR_FREQUENCY_UNSPECIFIED` and `--duration-s 0`
  selects `XR_MIN_HAPTIC_DURATION`. Both defaults work on every conformant
  runtime, so leave them at zero unless you need a specific waveform.
- The OpenXR controller haptic adapter is the canonical example of an
  `IHapticDevice` that needs a session reference at write-time. See the
  design doc (`IsaacLab/docs/tactile_haptic_feedback_design.md`, §4.7 and
  §5.6) for the architectural rationale.

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
uv run openxr_controller_haptic_example.py
```

## See also

- **Design doc:** `IsaacLab/docs/tactile_haptic_feedback_design.md`
- **Haptic adapters:** `isaacteleop.haptic_devices`
- **Per-device mappers:** `isaacteleop.retargeters.tactile_retargeters`
- **Sink:** `isaacteleop.retargeting_engine.deviceio_source_nodes.HapticSink`
