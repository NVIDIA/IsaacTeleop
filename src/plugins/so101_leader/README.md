<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SO-101 Leader Arm plugin

Streams the SO-101 (5-DOF arm + gripper) leader joint angles as a `JointStateOutput` FlatBuffer
over the OpenXR tensor transport, using the generic **joint-space device** path
(`JointStateTracker` / `JointStateSource` / `JointStateRetargeter`).

The SO-101 reads 6 Feetech STS3215 bus servos over a serial port. To keep the example
hardware-free and headless, the plugin ships a **synthetic backend** by default; the real
Feetech/serial read is the marked seam in `So101LeaderPlugin::read_hardware()`.

## Run

```bash
# Synthetic backend (no hardware):
./install/plugins/so101_leader/so101_leader_plugin

# With a serial device path + custom collection id (real backend is a TODO seam):
./install/plugins/so101_leader/so101_leader_plugin /dev/ttyACM0 so101_leader
```

The consumer side creates a `JointStateTracker("so101_leader")` (via
`JointStateSource(name=..., collection_id="so101_leader", joint_names=[...])`) on the same
`collection_id`. See `examples/teleop/python/joint_space_device_example.py` for the retargeting
pipeline (joint-mirror and task-space EE modes).

DOF order / names: `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`.
