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

**session** (`session.hpp/cpp`) - OpenXR initialization and session management
```cpp
class Session {
    bool initialize(const SessionConfig& config);
    const SessionHandles& handles() const;
};
```

**controllers** (`controllers.hpp/cpp`) - Controller input tracking
```cpp
class Controllers {
    bool initialize(XrInstance, XrSession, XrSpace);
    bool update(XrTime time);
    const ControllerPose& left() const;
    const ControllerPose& right() const;
};
```

**hand_generator** (`hand_generator.hpp/cpp`) - Hand joint generation
```cpp
class HandGenerator {
    void generate(XrHandJointLocationEXT* joints,
                  const XrPosef& wrist_pose,
                  bool is_left_hand);
};
```

**hand_injector** (`hand_injector.hpp/cpp`) - Push device data injection
```cpp
class HandInjector {
    bool initialize(XrInstance, XrSession, XrSpace);
    bool push_left(const XrHandJointLocationEXT*, XrTime);
    bool push_right(const XrHandJointLocationEXT*, XrTime);
};
```

### Data Flow

```
Controllers → Wrist Pose → Hand Generator → Hand Injector → OpenXR Runtime
```

## Implementation

### Main Loop

```cpp
Session session;
session.initialize(config);
auto h = session.handles();

Controllers controllers;
controllers.initialize(h.instance, h.session, h.reference_space);

HandGenerator hands;

HandInjector injector;
injector.initialize(h.instance, h.session, h.reference_space);

while (running) {
    controllers.update(time);

    auto left = controllers.left();
    if (left.grip_valid && left.aim_valid) {
        XrPosef wrist;
        wrist.position = left.grip_pose.position;
        wrist.orientation = left.aim_pose.orientation;

        hands.generate(joints, wrist, true);
        injector.push_left(joints, time);
    }
}
```

### Using Individual Components

#### Session Initialization

```cpp
#include "plugin_utils/session.hpp"

SessionConfig config;
config.app_name = "MyApp";
config.extensions = {"XR_EXT_hand_tracking"};

Session session;
session.initialize(config);
auto handles = session.handles();
```

#### Controller Tracking

```cpp
#include "plugin_utils/controllers.hpp"

Controllers controllers;
controllers.initialize(instance, session, space);

controllers.update(time);
auto left = controllers.left();
```

#### Hand Generation

```cpp
#include "hand_generator.hpp"

HandGenerator generator;
XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
generator.generate(joints, wrist_pose, true);
```

#### Hand Injection

```cpp
#include "plugin_utils/hand_injector.hpp"

HandInjector injector;
injector.initialize(instance, session, space);
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

All components use RAII - resources acquired in `initialize()`, released in destructor.

### Dependencies

```
controller_synthetic_hands.cpp
    ├── session (standalone)
    ├── controllers (requires OpenXR handles)
    ├── hand_generator (standalone)
    └── hand_injector (requires OpenXR handles)
```

## Extension Points

### New Input Sources

```cpp
class HandTrackingInput {
    bool initialize(XrInstance, XrSession);
    bool update(XrTime);
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
    Controllers controllers;
    EXPECT_TRUE(controllers.initialize(mock.instance, mock.session, mock.space));
}

TEST(HandGenerator, GeneratesCorrectJointCount) {
    HandGenerator gen;
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
    XrPosef wrist = {{0,0,0,1}, {0,0,0}};
    gen.generate(joints, wrist, true);
    // Verify joints
}
```

### Integration Tests

```cpp
TEST(Integration, FullPipeline) {
    Session session;
    session.initialize(test_config);
    auto h = session.handles();

    Controllers controllers;
    controllers.initialize(h.instance, h.session, h.reference_space);

    HandGenerator gen;
    HandInjector injector;
    injector.initialize(h.instance, h.session, h.reference_space);

    controllers.update(0);
    auto ctrl = controllers.left();
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
    XrPosef wrist = {ctrl.grip_pose.position, ctrl.aim_pose.orientation};
    gen.generate(joints, wrist, true);
    EXPECT_TRUE(injector.push_left(joints, 0));
}
```

## License

Copyright 2025, NVIDIA CORPORATION.
SPDX-License-Identifier: BSL-1.0
