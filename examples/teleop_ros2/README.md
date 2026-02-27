<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Reference (Python)

Reference ROS 2 publisher for Isaac Teleop data.

## Prerequisite: Start CloudXR Runtime

Before running this ROS 2 reference publisher, start the CloudXR runtime (see the `README.md` setup flow, step "Run CloudXR"):

```bash
./scripts/run_cloudxr.sh
```

## Published Topics

- `xr_teleop/hand` (`geometry_msgs/PoseArray`)
  - `poses[0]`: Right hand wrist pose (if active)
  - `poses[1]`: Left hand wrist pose (if active)
  - `poses[2+]`: Finger joint poses (all joints except palm/wrist, right then left)
- `xr_teleop/root_twist` (`geometry_msgs/TwistStamped`)
- `xr_teleop/root_pose` (`geometry_msgs/PoseStamped`)
- `xr_teleop/controller_data` (`std_msgs/ByteMultiArray`, msgpack-encoded dictionary)

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

### Overriding parameters

It's possible to set ROS 2 parameters from the command line when running the container. Append `--ros-args -p param_name:=value` after the image name:

```bash
docker run --rm --net=host --ipc=host \
  -e XR_RUNTIME_JSON -e NV_CXR_RUNTIME_DIR \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $CXR_HOST_VOLUME_PATH:$CXR_HOST_VOLUME_PATH:ro \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p frame_id:=odom -p rate_hz:=30.0
```

Available parameters: `hand_topic`, `twist_topic`, `pose_topic`, `controller_topic`, `full_body_topic`, `frame_id`, `rate_hz`, `use_mock_operators`. Use `ros2 param list /teleop_ros2_publisher` and `ros2 param describe /teleop_ros2_publisher <param>` (with the node running) for the full set.

## Echo Topics

```bash
docker exec -it teleop_ros2_ref /bin/bash

ros2 topic echo /xr_teleop/hand geometry_msgs/msg/PoseArray
ros2 topic echo /xr_teleop/root_twist geometry_msgs/msg/TwistStamped
ros2 topic echo /xr_teleop/root_pose geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/controller_data std_msgs/msg/ByteMultiArray
ros2 topic echo /xr_teleop/full_body std_msgs/msg/ByteMultiArray
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
