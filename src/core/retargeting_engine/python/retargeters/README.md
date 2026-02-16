<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Dex Hand Retargeters

This directory contains retargeters for Isaac Teleop's retargeting framework.

## Available Retargeters

### DexHandRetargeter

Accurate hand tracking retargeter using the `dex-retargeting` library.

**Features:**
- Uses optimization-based retargeting for accurate joint angle estimation
- Supports custom robot hands via URDF and YAML configuration
- Handles OpenXR hand tracking data (26 joints) → robot-specific joint angles
- Configurable coordinate frame transformations

**Requirements:**
- `dex-retargeting` library: `pip install dex-retargeting`
- `scipy`: `pip install scipy`
- Robot hand URDF file
- dex_retargeting YAML configuration file

**Configuration:**

```python
from isaacteleop.retargeting_engine import (
    DexHandRetargeter,
    DexHandRetargeterConfig,
)

config = DexHandRetargeterConfig(
    hand_joint_names=[
        "thumb_proximal_yaw_joint",
        "thumb_proximal_pitch_joint",
        "index_proximal_joint",
        "middle_proximal_joint",
        "ring_proximal_joint",
        "pinky_proximal_joint",
    ],
    hand_retargeting_config="/path/to/hand_config.yml",
    hand_urdf="/path/to/robot_hand.urdf",
    handtracking_to_baselink_frame_transform=(0, 0, 1, 1, 0, 0, 0, 1, 0),  # 3x3 matrix flattened
    hand_side="left",  # or "right"
)

retargeter = DexHandRetargeter(config, name="dex_hand_left")
```

**YAML Configuration Example:**

A typical config looks like:

```yaml
retargeting:
  finger_tip_link_names:
  - thumb_tip
  - index_tip
  - middle_tip
  - ring_tip
  - pinky_tip
  low_pass_alpha: 0.2
  scaling_factor: 1.2
  target_joint_names:
  - thumb_proximal_yaw_joint
  - thumb_proximal_pitch_joint
  - index_proximal_joint
  - middle_proximal_joint
  - ring_proximal_joint
  - pinky_proximal_joint
  type: DexPilot
  urdf_path: /path/to/robot_hand.urdf
  wrist_link_name: hand_base_link
```

### DexBiManualRetargeter

Bimanual wrapper around two `DexHandRetargeter` instances for controlling both hands simultaneously.

**Configuration:**

```python
from isaacteleop.retargeting_engine import (
    DexBiManualRetargeter,
    DexHandRetargeterConfig,
)

left_config = DexHandRetargeterConfig(
    hand_joint_names=left_hand_joints,
    hand_retargeting_config="/path/to/left_hand_config.yml",
    hand_urdf="/path/to/left_hand.urdf",
    hand_side="left",
)

right_config = DexHandRetargeterConfig(
    hand_joint_names=right_hand_joints,
    hand_retargeting_config="/path/to/right_hand_config.yml",
    hand_urdf="/path/to/right_hand.urdf",
    hand_side="right",
)

# Combined joint names for both hands
target_joint_names = left_hand_joints + right_hand_joints

bimanual_retargeter = DexBiManualRetargeter(
    left_config=left_config,
    right_config=right_config,
    target_joint_names=target_joint_names,
    name="dex_bimanual",
)
```

### TriHandMotionControllerRetargeter

Simple VR controller-based hand control. Maps trigger and squeeze inputs to G1 TriHand finger joint angles.

**Features:**
- No external dependencies (works out of the box)
- Simple mapping: trigger → index, squeeze → middle, both → thumb
- Good for quick prototyping and testing
- Outputs 7 DOF hand control

**Configuration:**

```python
from isaacteleop.retargeting_engine import (
    TriHandMotionControllerRetargeter,
    TriHandMotionControllerConfig,
)

config = TriHandMotionControllerConfig(
    hand_joint_names=[
        "thumb_rotation",
        "thumb_proximal",
        "thumb_distal",
        "index_proximal",
        "index_distal",
        "middle_proximal",
        "middle_distal",
    ],
    controller_side="left",  # or "right"
)

controller = TriHandMotionControllerRetargeter(config, name="trihand_motion_left")
```

**Output DOF Mapping:**
- Index 0: Thumb rotation (controlled by trigger - squeeze difference)
- Index 1: Thumb proximal joint (controlled by max(trigger, squeeze) * 0.4)
- Index 2: Thumb distal joint (controlled by max(trigger, squeeze) * 0.7)
- Index 3: Index finger proximal (controlled by trigger)
- Index 4: Index finger distal (controlled by trigger)
- Index 5: Middle finger proximal (controlled by squeeze)
- Index 6: Middle finger distal (controlled by squeeze)

### TriHandBiManualMotionControllerRetargeter

Bimanual wrapper around two `TriHandMotionControllerRetargeter` instances.

## Usage Example

See `g1_trihand_retargeting_example.py` for a complete working example.

```python
from isaacteleop.retargeting_engine.deviceio_source_nodes import HandsSource
from isaacteleop.retargeting_engine import DexHandRetargeter, DexHandRetargeterConfig
import isaacteleop.deviceio as deviceio

# Initialize hands source (tracker is internal)
hands_source = HandsSource(name="hands")

# Configure retargeter
config = DexHandRetargeterConfig(
    hand_joint_names=["thumb_joint", "index_joint", ...],
    hand_retargeting_config="/path/to/config.yml",
    hand_urdf="/path/to/hand.urdf",
    hand_side="left",
)

retargeter = DexHandRetargeter(config, name="dex_hand_left")

# Connect and compute
connected = retargeter.connect({
    "hand_left": hands_source.output("hand_left")
})

# Note: In a real application, use TeleopSession to run the pipeline
# output = connected.compute()
# joint_angles = output["hand_joints"]
```

## Coordinate Frame Transformations

The `handtracking_to_baselink_frame_transform` parameter is a 3x3 rotation matrix flattened to 9 elements.

**Common Transformations:**

- **G1/Inspire Frame** (default): `(0, 0, 1, 1, 0, 0, 0, 1, 0)`
  - Maps OpenXR tracking frame to robot base frame
  - Swap Z→X, X→Y, Y→Z

- **Identity** (no transformation): `(1, 0, 0, 0, 1, 0, 0, 0, 1)`

Matrix is applied as: `target_pos = joint_pos @ wrist_rotation @ transform_matrix`

## Future Improvements

- [ ] Add visualization support using Isaac Teleop's visualization system
- [ ] Add example config files for common robot hands
- [ ] Add support for downloading URDFs from URLs
- [ ] Add performance optimizations for real-time use
- [ ] Add tests for retargeting accuracy
