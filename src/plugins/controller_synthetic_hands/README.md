<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Controller Synthetic Hands

Generates hand tracking data from controller poses and injects it into the OpenXR runtime.

## Overview

Reads controller grip and aim poses, generates realistic hand joint configurations, and pushes the data to the runtime via push devices.

## Quick Start

### Build

```bash
cd build
cmake ..
make controller_synthetic_hands
```

### Run

```bash
./controller_synthetic_hands
```

Press Ctrl+C to exit.

## Architecture

### Components

Four focused components:

**session** (`oxr/oxr_session.hpp`) - OpenXR initialization and session management (from core)
```cpp
class OpenXRSession {
    OpenXRSession(const std::string& app_name, const std::vector<std::string>& extensions);
    OpenXRSessionHandles get_handles() const;
};
```

**controllers** (`controllers.hpp/cpp`) - Controller input tracking
```cpp
class Controllers {
    Controllers(XrInstance, XrSession, XrSpace);
    void update(XrTime time);
    const ControllerPose& left() const;
    const ControllerPose& right() const;
};
```

**hand_generator** (`hand_generator.hpp/cpp`) - Hand joint generation
```cpp
class HandGenerator {
    void generate(XrHandJointLocationEXT* joints,
                  const XrPosef& wrist_pose,
                  bool is_left_hand,
                  float curl = 0.0f);
};
```

**hand_injector** (`hand_injector.hpp/cpp`) - Push device data injection
```cpp
class HandInjector {
    HandInjector(XrInstance, XrSession, XrSpace);
    void push_left(const XrHandJointLocationEXT*, XrTime);
    void push_right(const XrHandJointLocationEXT*, XrTime);
};
```

### Data Flow

```
Controllers → Wrist Pose → Hand Generator → Hand Injector → OpenXR Runtime
```

## Implementation

### Main Loop

```cpp
#include <deviceio/controller_tracker.hpp>
#include <deviceio/deviceio_session.hpp>
#include <oxr_utils/pose_conversions.hpp>

// Create controller tracker and get required extensions
auto controller_tracker = std::make_shared<core::ControllerTracker>();
std::vector<std::shared_ptr<core::ITracker>> trackers = { controller_tracker };
auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

// Create session with required extensions
auto session = std::make_shared<core::OpenXRSession>("MyApp", extensions);
auto h = session->get_handles();

// Create DeviceIOSession to manage trackers
auto deviceio_session = core::DeviceIOSession::run(trackers, h);

HandGenerator hands;
HandInjector injector(h.instance, h.session, h.space);

while (running) {
    deviceio_session->update();

    const auto& left_ctrl = controller_tracker->get_left_controller(*deviceio_session);
    if (left_ctrl.is_active()) {
        bool grip_valid, aim_valid;
        oxr_utils::get_grip_pose(left_ctrl, grip_valid);
        XrPosef wrist = oxr_utils::get_aim_pose(left_ctrl, aim_valid);

        if (grip_valid && aim_valid) {
            float trigger = left_ctrl.inputs().trigger_value();
            hands.generate(joints, wrist, true, trigger);
            injector.push_left(joints, time);
        }
    }
}
```

### Using Individual Components

#### Session Initialization

```cpp
#include <oxr/oxr_session.hpp>

auto session = std::make_shared<core::OpenXRSession>("MyApp", {"XR_EXT_hand_tracking"});
auto handles = session->get_handles();
// handles.instance, handles.session, handles.space are available
```

#### Controller Tracking

```cpp
#include <deviceio/controller_tracker.hpp>
#include <deviceio/deviceio_session.hpp>
#include <oxr_utils/pose_conversions.hpp>

auto controller_tracker = std::make_shared<core::ControllerTracker>();
std::vector<std::shared_ptr<core::ITracker>> trackers = { controller_tracker };
auto deviceio_session = core::DeviceIOSession::run(trackers, handles);

deviceio_session->update();
const auto& left_ctrl = controller_tracker->get_left_controller(*deviceio_session);
const auto& right_ctrl = controller_tracker->get_right_controller(*deviceio_session);
// Use left_ctrl and right_ctrl (const ControllerSnapshot&)
```

#### Hand Generation

```cpp
#include "hand_generator.hpp"

HandGenerator generator;
XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
generator.generate(joints, wrist_pose, true, curl_value);
```

#### Hand Injection

```cpp
#include <plugin_utils/hand_injector.hpp>

HandInjector injector(instance, session, space);
injector.push_left(joints, timestamp);
```

## Technical Details

### Hand Joint Generation

Generates 26 joints per hand with anatomically correct positions and orientations. Joint offsets are defined in meters relative to the wrist, then rotated by the wrist orientation.

Coordinate system for left hand:
- X-axis: positive = thumb side, negative = pinky side
- Y-axis: positive = back of hand, negative = palm side
- Z-axis: positive = forward (fingers pointing), negative = toward wrist

Right hand is mirrored on the X-axis.

### Resource Management

All components use RAII - resources acquired in constructor, released in destructor.

### Dependencies

```
controller_synthetic_hands.cpp
    ├── oxr_session (from core, standalone)
    ├── controllers (requires OpenXR handles)
    ├── hand_generator (standalone)
    └── hand_injector (requires OpenXR handles)
```

## Extension Points

### New Input Sources

```cpp
class HandTrackingInput {
    HandTrackingInput(XrInstance, XrSession);
    void update(XrTime);
    const HandData& left() const;
};
```

### Data Recording

```cpp
class HandDataRecorder {
    void record(const XrHandJointLocationEXT*, XrTime);
};
```

### Gesture Recognition

```cpp
class GestureRecognizer {
    Gesture recognize(const XrHandJointLocationEXT*);
};
```
