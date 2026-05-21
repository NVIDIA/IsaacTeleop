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
| `hand_pinch_haptic_example.py` | Hand-tracking joint poses (XR_EXT_hand_tracking) | Manus glove (default) or OpenXR controller | Per-finger vibration driven by the distance from each finger tip to the thumb tip. The closer the finger to the thumb, the stronger the buzz on *both* pads. |

## Pinch-proximity haptics (`hand_pinch_haptic_example.py`)

Reads `HandsSource` joint poses, computes the Euclidean distance from each
finger tip to the thumb tip per hand, and ramps that distance into per-finger
vibration amplitudes. As the finger approaches the thumb the vibration grows;
when you actually touch them together both pads buzz at the saturation
amplitude. Works on either hand; the two hands are independent.

### Pipeline (`--device manus`, default)

```
HandsSource (left + right)
        |
        v
PinchProximityToFingerPower (HandInput -> FingerPowerVector(5))
        |
        v
HapticSink(ManusHapticDevice())
```

### Pipeline (`--device openxr_controller`)

Collapses per-finger powers to a single controller pulse so the demo works on
a Quest/Index without Manus hardware -- useful as a hand-tracking smoke test.
Reuses the `ControllerTracker` from `ControllersSource` to avoid spawning two
competing `LiveControllerTrackerImpl` instances.

```
HandsSource (left + right)              ControllersSource (tracker handle only)
        |                                                       |
        v                                                       |
PinchProximityToFingerPower                                     |
        |                                                       |
        v                                                       |
FingerPowerToControllerPulse (max across fingers)               |
        |                                                       |
        v                                                       v
HapticSink(OpenXRControllerHapticDevice())  ->  OpenXRControllerHapticSource
                                                  poll_tracker(session)
```

### Usage

```bash
# Default: Manus per-finger haptics. Pinch any finger toward the thumb.
uv run hand_pinch_haptic_example.py

# Loosen the ramp so vibration kicks in at 15 cm and saturates at 1 cm.
uv run hand_pinch_haptic_example.py --max-distance-m 0.15 --min-distance-m 0.01

# Steeper falloff -- only register a strong pinch when very close.
uv run hand_pinch_haptic_example.py --falloff-exponent 2.5

# Same demo on OpenXR controllers (no Manus needed). Both controllers rumble
# with the strongest finger-to-thumb proximity on their respective hand.
uv run hand_pinch_haptic_example.py --device openxr_controller
```

### Notes

- Requires an XR runtime that exposes `XR_EXT_hand_tracking`. Quest 3 (via
  CloudXR or native), Manus gloves with optical fallback, and Vive Index with
  hand-tracking add-ons all satisfy this. Without hand tracking the
  retargeter sees `is_none` and quietly outputs zero amplitude.
- `--device manus` requires the Manus plugin to have already been started so
  the singleton is alive (see `src/plugins/manus/README.md`). When the plugin
  is not built or no glove is connected, the per-side adapter logs once and
  silently no-ops -- the rest of the session keeps running.
- The retargeter's tunable parameters (`--max-distance-m`, `--saturation`,
  `--falloff-exponent`) are constructor-time only in this example. The
  production tuning-UI flow lives on the
  `isaacteleop.retargeters.tactile_retargeters` mappers, which carry a
  `ParameterState` for live adjustment from the existing
  `MultiRetargeterTuningUIImGui` panel.

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
