<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS2 Reference (Python)

Reference ROS2 bridge for Isaac Teleop data. It publishes the same topic set as
`xr_teleop_ros2` using standard ROS2 message types.

## Published Topics

- `xr_teleop/hand` (`geometry_msgs/PoseArray`)
  - `poses[0]`: Right hand wrist pose (if active)
  - `poses[1]`: Left hand wrist pose (if active)
  - `poses[2+]`: Finger joint poses (all joints except palm/wrist, right then left)
- `xr_teleop/root_twist` (`geometry_msgs/TwistStamped`)
- `xr_teleop/root_pose` (`geometry_msgs/PoseStamped`)
- `xr_teleop/controller_data` (`std_msgs/ByteMultiArray`, msgpack-encoded dictionary)

## Run in Docker (ROS2 Humble)

### Build the container

From the repo root:
```bash
docker build -f examples/teleop_ros2/Dockerfile -t teleop_ros2_ref .
```

Incremental rebuilds use Docker BuildKit cache. Ensure BuildKit is enabled (default in Docker 23+), or run with `DOCKER_BUILDKIT=1 docker build ...`.

### Run the container

Use host networking (recommended for ROS2 DDS):
```bash
docker run --rm --net=host \
  teleop_ros2_ref \
  --use-mock-operators
```

## Echo Topics

```bash
ros2 topic echo /xr_teleop/hand geometry_msgs/msg/PoseArray
ros2 topic echo /xr_teleop/root_twist geometry_msgs/msg/TwistStamped
ros2 topic echo /xr_teleop/root_pose geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/controller_data std_msgs/msg/ByteMultiArray
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
