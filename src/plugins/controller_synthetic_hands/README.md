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
cd TeleopCore/build
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
    static std::shared_ptr<OpenXRSession> Create(const std::string& app_name,
                                                 const std::vector<std::string>& extensions = {});
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
auto session = core::OpenXRSession::Create("MyApp", {XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME});
auto h = session->get_handles();

Controllers controllers(h.instance, h.session, h.space);

HandGenerator hands;

HandInjector injector(h.instance, h.session, h.space);

while (running) {
    controllers.update(time);

    auto left = controllers.left();
    if (left.grip_valid && left.aim_valid) {
        XrPosef wrist;
        wrist.position = left.grip_pose.position;
        wrist.orientation = left.aim_pose.orientation;

        hands.generate(joints, wrist, true, left.trigger_value);
        injector.push_left(joints, time);
    }
}
```

### Using Individual Components

#### Session Initialization

```cpp
#include <oxr/oxr_session.hpp>

auto session = core::OpenXRSession::Create("MyApp", {"XR_EXT_hand_tracking"});
auto handles = session->get_handles();
// handles.instance, handles.session, handles.space are available
```

#### Controller Tracking

```cpp
#include <plugin_utils/controllers.hpp>

Controllers controllers(instance, session, space);

controllers.update(time);
auto left = controllers.left();
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

## Testing

### Unit Tests

```cpp
TEST(Controllers, InitializeSucceeds) {
    auto mock = create_mock_handles();
    Controllers controllers(mock.instance, mock.session, mock.space);
    // Validation happens in constructor (throws on failure)
}

TEST(HandGenerator, GeneratesCorrectJointCount) {
    HandGenerator gen;
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
    XrPosef wrist = {{0,0,0,1}, {0,0,0}};
    gen.generate(joints, wrist, true, 0.0f);
    // Verify joints
}
```

### Integration Tests

```cpp
TEST(Integration, FullPipeline) {
    auto session = core::OpenXRSession::Create("TestApp");
    auto h = session->get_handles();

    Controllers controllers(h.instance, h.session, h.space);

    HandGenerator gen;
    HandInjector injector(h.instance, h.session, h.space);

    controllers.update(0);
    auto ctrl = controllers.left();
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
    XrPosef wrist = {ctrl.grip_pose.position, ctrl.aim_pose.orientation};
    gen.generate(joints, wrist, true, 0.0f);
    injector.push_left(joints, 0);
}
```

## License

Copyright 2025, NVIDIA CORPORATION.
SPDX-License-Identifier: BSL-1.0
