<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SpaceMouse Plugin

Reads a 3Dconnexion SpaceMouse-family device from `/dev/hidraw*` and pushes `SpaceMouseOutput`
via OpenXR. Use with `SpaceMouseTracker` with the same `collection_id`.

Reports raw axis/button state only, with no semantic mapping to position, rotation, or
commands -- that mapping belongs in a retargeter (e.g. `SpaceMouseToSe3RelRetargeter`)
consuming this tracker's output.

Self-discovers its device (the first hidraw device under `/sys/class/hidraw/` whose
`HID_NAME` matches a validated product name), so it needs no arguments to run and can be
auto-launched by `PluginManager` via `PluginConfig` -- no manual process to start.

## Usage

Auto-launched (recommended -- matches how `PluginManager` invokes plugins):

```bash
./spacemouse_plugin --plugin-root-id=spacemouse
```

Manual / standalone, with an explicit device:

```bash
./spacemouse_plugin [device_path] [--combined-report] [--plugin-root-id=<collection_id>]
```

- **device_path**: Optional. Defaults to the first matching hidraw device under
  `/sys/class/hidraw/`. Identify a specific device with
  `cat /sys/class/hidraw/hidraw*/device/uevent` (look for a `HID_NAME=` line) or `lsusb`.
  Reading `/dev/hidraw*` typically requires membership in the `input` group (or a udev
  rule granting access).
- **--combined-report**: Only needed with an explicit device path for a "3Dconnexion
  Universal Receiver" (auto-discovery sets this automatically); packs translation and
  rotation into a single 13-byte report instead of two separate 7-byte reports.
- **collection_id**: Default `spacemouse`. Match this when creating `SpaceMouseTracker`.

## Validated devices

- SpaceMouse Compact
- SpaceMouse Wireless
- SpaceNavigator for Notebooks
- 3Dconnexion Universal Receiver

## Axis/button mapping

Reports the current translation (`[x, y, z]`) and rotation (`[x, y, z]`) axis readings,
normalized to `[-1, 1]`, and the set of currently-held button indices (bit position in the
device's button report byte). Linux only.
