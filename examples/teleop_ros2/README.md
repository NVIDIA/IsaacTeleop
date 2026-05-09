<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Reference (Python)

Reference ROS 2 publisher for Isaac Teleop data.

## Prerequisite: Start CloudXR Runtime

Before running this ROS 2 reference publisher, start the CloudXR runtime via Docker (see the `README.md` setup flow, step "Run CloudXR"):

1. To use optical hand tracking from the XR device, create a CloudXR environment file `deps/cloudxr/.env` (if missing) with:

```bash
NV_CXR_ENABLE_PUSH_DEVICES=0
```

1. Start CloudXR:

```bash
./scripts/run_cloudxr_via_docker.sh
```

## Prerequisite: Foot Pedal For `hand_teleop`

`hand_teleop` uses `Generic3AxisPedalSource` + `FootPedalRootCmdRetargeter` for
`xr_teleop/root_twist` and `xr_teleop/root_pose`. Start `foot_pedal_reader`,
`pedal_pusher`, or a compatible pedal plugin so pedal data is available through
the matching collection ID.

The default collection ID is `generic_3axis_pedal`. Override it with
`--ros-args -p pedal_collection_id:=<your_collection_id>` when your pedal
publisher uses a different ID.

## Prerequisite: Hand Retargeting For `hand_teleop`

`hand_teleop` retargets OpenXR hand tracking to Sharpa hand joint commands via
the `hand_retargeter` parameter:

- `hand_retargeter:=pink_ik` (default): uses `SharpaHandRetargeter`. It requires the
  `isaacteleop[grounding]` runtime dependencies and the bundled
  `robotic_grounding` package data that provides the Sharpa MJCF assets.
- `hand_retargeter:=dexpilot`: uses `DexHandRetargeter` with DexPilot configs from
  `examples/teleop_ros2/configs/`. It requires `isaacteleop[retargeters]` and
  manually supplied or generated standalone Sharpa Wave URDFs at:
  `examples/teleop_ros2/assets/urdf/sharpa_standalone/left_sharpa_wave.urdf`
  and
  `examples/teleop_ros2/assets/urdf/sharpa_standalone/right_sharpa_wave.urdf`.

When running from the Docker image, that asset directory is installed at
`/opt/isaacteleop/install/examples/teleop_ros2/assets/urdf/sharpa_standalone/`.
These URDF assets are not fetched at runtime.

## Published Topics

- `xr_teleop/hand` (`geometry_msgs/PoseArray`)
  - `poses`: Finger joint poses (all joints except palm/wrist, right then left)
- `xr_teleop/ee_poses` (`geometry_msgs/PoseArray`)
  - `poses[0]`: Left hand/controller EE pose (if active)
  - `poses[1]`: Right hand/controller EE pose (if active)
- `xr_teleop/root_twist` (`geometry_msgs/TwistStamped`)
- `xr_teleop/root_pose` (`geometry_msgs/PoseStamped`)
- `xr_teleop/controller_data` (`std_msgs/ByteMultiArray`, msgpack-encoded dictionary)
- `xr_teleop/finger_joints` (`sensor_msgs/JointState`)
  - Retargeted finger joint angles for the robot; contains joint names and position arrays corresponding to the robot finger joints (TriHand in `controller_teleop`, selected Sharpa retargeter in `hand_teleop`)
- `/tf` (`tf2_msgs/TFMessage`)
  - `world_frame` → `right_wrist_frame`: Right wrist transform (published in `controller_teleop` and `hand_teleop` modes)
  - `world_frame` → `left_wrist_frame`: Left wrist transform (published in `controller_teleop` and `hand_teleop` modes)

## Run in Docker

### Build the container

From the repo root.

**Humble (default):**
```bash
docker build -f examples/teleop_ros2/Dockerfile -t teleop_ros2_ref .
```

**Jazzy:**
```bash
docker build -f examples/teleop_ros2/Dockerfile --build-arg ROS_DISTRO=jazzy --build-arg PYTHON_VERSION=3.12 -t teleop_ros2_ref:jazzy .
```

You can tag by distro (e.g. `teleop_ros2_ref:humble`, `teleop_ros2_ref:jazzy`) to build and run both side by side.

Incremental rebuilds use Docker BuildKit cache. Ensure BuildKit is enabled (default in Docker 23+), or run with `DOCKER_BUILDKIT=1 docker build ...`.

### Run the container

Use host networking (recommended for ROS 2 DDS):
```bash
source scripts/setup_cloudxr_env.sh
docker run --rm --net=host --ipc=host \
  -e XR_RUNTIME_JSON -e NV_CXR_RUNTIME_DIR \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $CXR_HOST_VOLUME_PATH:$CXR_HOST_VOLUME_PATH:ro \
  --name teleop_ros2_ref \
  teleop_ros2_ref
```

### Overriding parameters and remapping topics

It's possible to set ROS 2 parameters and remap topics from the command line when running the container. Append `--ros-args -p param_name:=value` to set parameters, or `--ros-args -r old_topic:=new_topic` to remap topics after the image name:

```bash
docker run --rm --net=host --ipc=host \
  -e XR_RUNTIME_JSON -e NV_CXR_RUNTIME_DIR \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $CXR_HOST_VOLUME_PATH:$CXR_HOST_VOLUME_PATH:ro \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p world_frame:=odom -p rate_hz:=30.0 \
  -r xr_teleop/hand:=my_robot/hand -r xr_teleop/ee_poses:=my_robot/ee_poses
```

Available parameters: `rate_hz`, `mode`, `hand_retargeter`, `pedal_collection_id`, `world_frame`, `right_wrist_frame`, `left_wrist_frame`, `left_finger_joint_names`, `right_finger_joint_names`. Use `ros2 param list /teleop_ros2_node` and `ros2 param describe /teleop_ros2_node <param>` (with the node running) for the full set.

By default, `left_finger_joint_names` and `right_finger_joint_names` use the selected mode's retargeter joint names. They can be overridden to publish robot-specific names on `xr_teleop/finger_joints`, but each override must provide the same number of names as the joints emitted by that mode's retargeter.

Available topics for remapping: `xr_teleop/hand`, `xr_teleop/ee_poses`, `xr_teleop/root_twist`, `xr_teleop/root_pose`, `xr_teleop/controller_data`, `xr_teleop/full_body`, `xr_teleop/finger_joints`. Active remaps can be inspected with `ros2 node info /teleop_ros2_node`.

### Mode

The `mode` parameter selects the teleoperation scenario and which topics are published:

| Mode | Topics published |
|------|------------------|
| `controller_teleop` (default) | `ee_poses` (from controller aim pose), `root_twist`, `root_pose`, `finger_joints` (finger joints in joint space), `controller_data`, `tf` (from controller aim pose) |
| `hand_teleop` | `ee_poses` (from hand tracking wrist), `hand` (finger joints in pose space), `finger_joints` (finger joints in joint space), `root_twist`, `root_pose`, `tf` (from hand tracking wrist); locomotion comes from the configured foot pedal collection |
| `controller_raw` | `controller_data` only |
| `full_body` | `full_body` and `controller_data` |

Example: `--ros-args -p mode:=controller_raw`

## Echo Topics

```bash
docker exec -it teleop_ros2_ref /bin/bash

ros2 topic echo /xr_teleop/hand geometry_msgs/msg/PoseArray
ros2 topic echo /xr_teleop/ee_poses geometry_msgs/msg/PoseArray
ros2 topic echo /xr_teleop/root_twist geometry_msgs/msg/TwistStamped
ros2 topic echo /xr_teleop/root_pose geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/controller_data std_msgs/msg/ByteMultiArray
ros2 topic echo /xr_teleop/full_body std_msgs/msg/ByteMultiArray
ros2 topic echo /xr_teleop/finger_joints sensor_msgs/msg/JointState
ros2 topic echo /tf tf2_msgs/msg/TFMessage
```

## Controller Data Decoding

```python
import msgpack
import msgpack_numpy as mnp
from std_msgs.msg import ByteMultiArray

def controller_callback(msg: ByteMultiArray):
    data = msgpack.unpackb(
        bytes([ab for a in msg.data for ab in a]),
        object_hook=mnp.decode,
    )
    print(data.keys())
```
