<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Reference (Python)

Reference ROS 2 publisher for Isaac Teleop data.

## Prerequisite: Foot Pedal For `hand_teleop`

`hand_teleop` uses `Generic3AxisPedalSource` + `FootPedalRootCmdRetargeter` for
`xr_teleop/root_twist` and `xr_teleop/root_pose`. Start `foot_pedal_reader`,
`pedal_pusher`, or a compatible pedal plugin so pedal data is available through
the matching collection ID.

The default collection ID is `generic_3axis_pedal`. Override it with
`--ros-args -p pedal_collection_id:=<your_collection_id>` when your pedal
publisher uses a different ID.

## Prerequisite: Hand Retargeting

`hand_teleop` and the Sharpa variants of `controller_teleop` retarget OpenXR
hand tracking to Sharpa hand joint commands via the `hand_retargeter`
parameter:

- `hand_retargeter:=mode_default` (default): keeps the mode-specific default
  behavior: `controller_teleop` uses TriHand controller retargeting, while
  `hand_teleop` uses DexPilot Sharpa retargeting.
- `hand_retargeter:=trihand`: valid only with `controller_teleop`; retargets
  controller trigger/squeeze input to TriHand finger joints.
- `hand_retargeter:=dexpilot`: uses `DexHandRetargeter` with DexPilot configs from
  `examples/teleop_ros2/configs/`. It requires `isaacteleop[retargeters]` and
  official standalone Sharpa Wave URDFs at:
  `examples/teleop_ros2/assets/urdf/sharpa_standalone/left_sharpa_wave.urdf`
  and
  `examples/teleop_ros2/assets/urdf/sharpa_standalone/right_sharpa_wave.urdf`.
  Set `config_asset_root` to use a different directory containing `configs/`
  and `assets/`; the empty default uses the installed or source example root.
- `hand_retargeter:=pink_ik`: uses `SharpaHandRetargeter`. It requires the
  `isaacteleop[grounding]` runtime dependencies and the bundled
  `robotic_grounding` package data that provides the Sharpa MJCF assets.

In `controller_teleop`, explicitly setting `hand_retargeter:=dexpilot` or
`hand_retargeter:=pink_ik` keeps XR controllers responsible for EE poses, wrist
TFs, locomotion, and `controller_data`, while Manus/OpenXR hand data drives
`xr_teleop/hand_left`, `xr_teleop/hand_right`, and Sharpa
`xr_teleop/finger_joints`.

The Docker build fetches the pinned official Sharpa Wave URDFs and installs them
at `/opt/isaacteleop/install/examples/teleop_ros2/assets/urdf/sharpa_standalone/`.
Source-tree users can populate the same local asset directory from the repo root:

```bash
python3 examples/teleop_ros2/scripts/fetch_sharpa_wave_urdfs.py
```

Robot assets are never downloaded by `teleop_ros2_node.py` at runtime.

## Published Topics

- `xr_teleop/hand_left` (`teleop_ros2_interfaces/msg/HandJointPoses`)
  - Named left OpenXR hand joint poses; `joints` has 25 entries, each with `name`, `pose`, and `valid`; includes `WRIST`, omits `PALM`
- `xr_teleop/hand_right` (`teleop_ros2_interfaces/msg/HandJointPoses`)
  - Named right OpenXR hand joint poses; `joints` has 25 entries, each with `name`, `pose`, and `valid`; includes `WRIST`, omits `PALM`
- `xr_teleop/ee_pose_left` (`geometry_msgs/PoseStamped`)
  - Left hand/controller EE pose; published when the left EE source is active
- `xr_teleop/ee_pose_right` (`geometry_msgs/PoseStamped`)
  - Right hand/controller EE pose; published when the right EE source is active
- `xr_teleop/root_twist` (`geometry_msgs/TwistStamped`)
- `xr_teleop/root_pose` (`geometry_msgs/PoseStamped`)
- `xr_teleop/head_pose` (`geometry_msgs/PoseStamped`)
  - Head pose
- `xr_teleop/controller_data` (`std_msgs/ByteMultiArray`, msgpack-encoded dictionary)
- `xr_teleop/finger_joints` (`sensor_msgs/JointState`)
  - Retargeted finger joint angles for the robot; contains joint names and position arrays corresponding to the robot finger joints (TriHand in default `controller_teleop`, selected Sharpa retargeter in `hand_teleop`, or explicit Sharpa retargeter in `controller_teleop`)
- `/tf` (`tf2_msgs/TFMessage`)
  - `world_frame` → `right_wrist_frame`: Right wrist transform (published in `controller_teleop` and `hand_teleop` modes)
  - `world_frame` → `left_wrist_frame`: Left wrist transform (published in `controller_teleop` and `hand_teleop` modes)
  - `world_frame` → `head_frame`: Head transform (published in `controller_teleop` and `hand_teleop` modes)

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
docker run --rm --gpus all --net=host --ipc=host \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $HOME/.cloudxr:/root/.cloudxr \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p cloudxr_accept_eula:=true
```

### Overriding parameters and remapping topics

It's possible to set ROS 2 parameters and remap topics from the command line when running the container. Append `--ros-args -p param_name:=value` to set parameters, or `--ros-args -r old_topic:=new_topic` to remap topics after the image name:

```bash
docker run --rm --gpus all --net=host --ipc=host \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $HOME/.cloudxr:/root/.cloudxr \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p cloudxr_accept_eula:=true \
  -p world_frame:=odom -p rate_hz:=30.0 \
  -r xr_teleop/hand_left:=my_robot/hand_left \
  -r xr_teleop/hand_right:=my_robot/hand_right \
  -r xr_teleop/ee_pose_left:=my_robot/ee_pose_left \
  -r xr_teleop/ee_pose_right:=my_robot/ee_pose_right
```

Available parameters: `rate_hz`, `mode`, `hand_retargeter`, `config_asset_root`, `cloudxr_install_dir`, `cloudxr_env_config`, `cloudxr_accept_eula`, `cloudxr_setup_oob`, `cloudxr_usb_local`, `pedal_collection_id`, `world_frame`, `right_wrist_frame`, `left_wrist_frame`, `head_frame`, `left_finger_joint_names`, `right_finger_joint_names`. Use `ros2 param list /teleop_ros2_node` and `ros2 param describe /teleop_ros2_node <param>` (with the node running) for the full set.

By default, `left_finger_joint_names` and `right_finger_joint_names` use the selected mode's retargeter joint names. They can be overridden to publish robot-specific names on `xr_teleop/finger_joints`, but each override must provide the same number of names as the joints emitted by that mode's retargeter.

Available topics for remapping: `xr_teleop/hand_left`, `xr_teleop/hand_right`, `xr_teleop/ee_pose_left`, `xr_teleop/ee_pose_right`, `xr_teleop/root_twist`, `xr_teleop/root_pose`, `xr_teleop/head_pose`, `xr_teleop/controller_data`, `xr_teleop/full_body`, `xr_teleop/finger_joints`. Active remaps can be inspected with `ros2 node info /teleop_ros2_node`.

### Mode

The `mode` parameter selects the teleoperation scenario and which topics are published:

| Mode | Topics published |
|------|------------------|
| `controller_teleop` (default) | `ee_pose_left`, `ee_pose_right` (from controller aim pose), `root_twist`, `root_pose`, `head_pose`, `finger_joints` (TriHand by default; Sharpa from Manus/OpenXR hands when `hand_retargeter:=dexpilot` or `hand_retargeter:=pink_ik`), `controller_data`, `tf` (from controller aim pose and head pose), and `hand_left`/`hand_right` only for the explicit Sharpa retargeter path |
| `hand_teleop` | `ee_pose_left`, `ee_pose_right` (from hand tracking wrist), `hand_left`/`hand_right` (named per-hand joint poses), `finger_joints` (finger joints in joint space), `root_twist`, `root_pose`, `head_pose`, `tf` (from hand tracking wrist and head pose); locomotion comes from the configured foot pedal collection |
| `controller_raw` | `controller_data` only |
| `full_body` | `full_body` and `controller_data` |

Example: `--ros-args -p mode:=controller_raw`

### OOB Teleop Control

For live sessions, the node can enable the out-of-band (OOB) teleop control hub
that the in-process `CloudXRLauncher` provides. The hub shares the CloudXR proxy
TLS port (default 48322) and lets you read streaming metrics, inspect connected
headsets, and push config from outside the headset:

```bash
docker run --rm --gpus all --net=host --ipc=host \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e ROS_LOCALHOST_ONLY=1 \
  -v $HOME/.cloudxr:/root/.cloudxr \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p cloudxr_accept_eula:=true \
  -p cloudxr_setup_oob:=true
```

`cloudxr_usb_local:=true` additionally routes teleop signalling, the web client,
and WebRTC media over the USB cable via `adb reverse`. It requires
`cloudxr_setup_oob:=true` (the node raises a parameter error otherwise) and the
`adb` and `coturn` host tools. Both parameters are ignored in MCAP replay mode,
since no CloudXR runtime is launched.

See the [Out-of-Band Teleop Control](../../docs/source/references/oob_teleop_control.rst)
reference for the hub HTTP/WebSocket API, ADB automation, and USB-local details.

### MCAP Replay

Set `mcap_replay_path` to run the same ROS 2 publisher from recorded DeviceIO
tracker data instead of live OpenXR/DeviceIO inputs:

```bash
docker run --rm --net=host --ipc=host \
  -v /tmp:/tmp \
  --name teleop_ros2_ref \
  teleop_ros2_ref --ros-args -p mode:=controller_raw \
  -p mcap_replay_path:=/tmp/teleop_ros2_input.mcap
```

The installed integration test utility
`examples/teleop_ros2/cpp/integration_tests/teleop_ros2_mcap_generator` creates a
deterministic fixture with controller, hand, pedal, and full-body samples for CI
coverage.

## Echo Topics

```bash
docker exec -it teleop_ros2_ref /bin/bash

ros2 topic echo /xr_teleop/hand_left teleop_ros2_interfaces/msg/HandJointPoses
ros2 topic echo /xr_teleop/hand_right teleop_ros2_interfaces/msg/HandJointPoses
ros2 topic echo /xr_teleop/ee_pose_left geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/ee_pose_right geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/root_twist geometry_msgs/msg/TwistStamped
ros2 topic echo /xr_teleop/root_pose geometry_msgs/msg/PoseStamped
ros2 topic echo /xr_teleop/head_pose geometry_msgs/msg/PoseStamped
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
