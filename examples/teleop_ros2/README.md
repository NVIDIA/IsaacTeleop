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

From the repo root:
```bash
docker build -f examples/teleop_ros2/Dockerfile -t teleop_ros2_ref .
```

Incremental rebuilds use Docker BuildKit cache. Ensure BuildKit is enabled (default in Docker 23+), or run with `DOCKER_BUILDKIT=1 docker build ...`.

### Run the container

Use host networking (recommended for ROS 2 DDS):
```bash
source scripts/setup_cloudxr_env.sh
docker run --rm --net=host \
  -e XR_RUNTIME_JSON -e NV_CXR_RUNTIME_DIR \
  -v $CXR_HOST_VOLUME_PATH:$CXR_HOST_VOLUME_PATH:ro \
  --name teleop_ros2_ref \
  teleop_ros2_ref
```

## Echo Topics

```bash
docker exec -it teleop_ros2_ref /bin/bash

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
