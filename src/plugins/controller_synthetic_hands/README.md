<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Controller Synthetic Hands

Generates hand tracking data from controller poses and publishes it through an
Isaac Teleop plugin session.

## Overview

The plugin reads controller grip and aim poses through an
`IPluginPullChannel`, generates a 26-joint hand pose, and publishes each active
hand through a `HandTrackingPusher`.

The executable is the composition root. It currently constructs an
`OpenXRPluginSession`, but the `SyntheticHandsPlugin` implementation depends
only on `IPluginSession` and can use another session adapter.

```text
ControllerTracker
      |
IPluginPullChannel --update()--> controller snapshot
      |
HandGenerator
      |
HandTrackingPusher --> IHandTrackingPushChannel --> session backend
```

The per-hand pusher is created when its controller becomes active and destroyed
when the controller disappears. Closing the channel marks that hand inactive
instead of leaving a frozen pose.

## Quick Start

### Build

```bash
cmake -S . -B build
cmake --build build --target controller_synthetic_hands
```

### Run

```bash
./build/src/plugins/controller_synthetic_hands/controller_synthetic_hands
```

Press Ctrl+C to exit.

## Plugin-facing setup

```cpp
auto controller_tracker = std::make_shared<core::ControllerTracker>();
std::vector<std::shared_ptr<core::ITracker>> trackers = {controller_tracker};

core::PluginSessionHandle session =
    std::make_shared<plugin_utils::OpenXRPluginSession>(
        "ControllerSyntheticHands",
        core::PluginSessionRequirements{.hand_tracking_push = true},
        std::move(trackers));

SyntheticHandsPlugin plugin(
    plugin_root_id, std::move(controller_tracker), std::move(session));
```

Only the composition root names the concrete adapter. Inside the plugin, one
tick is:

```cpp
pull_channel->update();
const auto& controller = controller_tracker->get_left_controller(*pull_channel);

if (controller) {
    hand_generator.generate(joints, wrist_pose, true, trigger_value);
    left_pusher->push(joints, sample_time_local_common_clock_ns);
}
```

## Hand generation

Joint offsets are defined in meters relative to the wrist and transformed by
the wrist pose. The left-hand coordinate conventions are:

- X: thumb side to pinky side
- Y: back of hand to palm
- Z: fingers to wrist

The right hand is mirrored on the X axis. OpenXR value structs describe the
established joint and pose layout; runtime handles and calls remain in the
concrete session adapter.
