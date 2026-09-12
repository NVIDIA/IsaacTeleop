<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Gamepad Plugin

Reads a gamepad from `/dev/input/js*` (Linux joystick API) and pushes `GamepadOutput` via OpenXR.
Use with `GamepadTracker` with the same `collection_id`.

Reports raw button/axis state only, with no semantic mapping to sticks, triggers, or commands --
that mapping belongs in a retargeter (e.g. `GamepadToSe3RelRetargeter`) consuming this tracker's
output.

Self-discovers its device (the first `*-joystick` entry under `/dev/input/by-path/`), so it needs
no arguments to run and can be auto-launched by `PluginManager` via `PluginConfig` -- no manual
process to start.

## Usage

Auto-launched (recommended -- matches how `PluginManager` invokes plugins):

```bash
./gamepad_plugin --plugin-root-id=gamepad
```

Manual / standalone, with an explicit device:

```bash
./gamepad_plugin [device_path] [--plugin-root-id=<collection_id>]
```

- **device_path**: Optional. Defaults to the first `*-joystick` entry under `/dev/input/by-path/`.
  Identify a specific gamepad with `cat /proc/bus/input/devices` (look for a `Handlers=... jsN`
  line under a gamepad entry) or `jstest /dev/input/jsN`. Reading `/dev/input/js*` typically
  requires membership in the `input` group.
- **collection_id**: Default `gamepad`. Match this when creating `GamepadTracker`.

## Button/axis mapping

Reports every axis value (normalized to `[-1, 1]`) and the set of currently-held button indices,
as reported by the Linux joystick API (`JS_EVENT_AXIS` / `JS_EVENT_BUTTON`, see
`linux/joystick.h`). Axis/button indices and count depend on the connected device's driver (e.g.
`xpad` for Xbox-style controllers) -- no fixed mapping is assumed here.

Linux only.
