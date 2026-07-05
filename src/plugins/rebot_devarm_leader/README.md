<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# reBot DevArm Leader Arm plugin

Streams the [Seeed reBot DevArm](https://github.com/Seeed-Projects/reBot-DevArm) (6-DOF arm +
gripper) leader joint angles as a `JointStateOutput` FlatBuffer over the OpenXR tensor transport,
using the generic **joint-space device** path
(`JointStateTracker` / `JointStateSource` / `JointStateRetargeter`).

The reBot DevArm is 7 Damiao DM-series MIT-protocol motors — DM4340P on joints 1–3, DM4310 on
joints 4–6 and the gripper — on a CAN bus behind a Damiao USB-to-CAN serial adapter (USB CDC-ACM,
the `dm-serial` transport also used by the vendor's DM_Control stack and the
[reBotArm_control_py](https://github.com/Seeed-Projects/reBotArm_control_py) reference code).
`DamiaoBus` (`damiao_bus.{hpp,cpp}`) speaks the adapter's fixed-size binary framing directly — no
SDK dependency — and implements just what a *leader* needs: send the **disable** control frame so
the arm can be back-driven by hand (Damiao motors keep answering feedback requests while
disabled), then request one feedback frame per motor per cycle (command `0xCC` addressed via CAN
id `0x7FF`) and decode position/velocity from the replies. Damiao feedback is fixed-point over
the model's `[-p_max, p_max]` / `[-v_max, v_max]` limits and lands directly in radians — no tick
conversion, only an optional per-joint sign and zero offset from a calibration file.

When no serial device is given, the plugin falls back to a **synthetic** trajectory so the
device → tracker → retargeter pipeline runs with no hardware (CI and headless bring-up).

## Run

```bash
# Synthetic backend (no hardware):
./install/plugins/rebot_devarm_leader/rebot_devarm_leader_plugin

# Real reBot DevArm on the Damiao USB-to-CAN adapter (Linux), default collection id
# "rebot_devarm_leader":
./install/plugins/rebot_devarm_leader/rebot_devarm_leader_plugin /dev/ttyACM0

# ... with a custom collection id and a calibration file:
./install/plugins/rebot_devarm_leader/rebot_devarm_leader_plugin /dev/ttyACM0 rebot_devarm_leader rebot_devarm.calib
```

Args are positional: `[device_path] [collection_id] [calibration_file]`. The serial backend is
Linux/macOS only (POSIX `termios`); the adapter enumerates as a CDC-ACM device (nominal 921600 bps).

## Probe the hardware (no OpenXR runtime)

The `probe` subcommand opens the bus, sends disable (back-drive mode), and streams decoded joint
positions to stdout — use it to verify wiring, motor ids, and the decode path before running the
full plugin:

```bash
./install/plugins/rebot_devarm_leader/rebot_devarm_leader_plugin probe /dev/ttyACM0
# probe:  joint1=0.0012  joint2=-0.0034  ...  gripper=0.0001
```

Exit code 0 means every motor replied at least once. Exit code 3 means every motor replied but
the gripper reads outside its physical travel: the Damiao multi-turn counter is volatile across
power cycles, so the gripper (whose geared travel exceeds one turn) can wake up reading
`physical + 2*pi*k`. Re-home it (close against the mechanical stop and re-zero) before
teleoperating — a wrapped reading would slam the follower's gripper into its soft-limit clip on
the first frame. While wrapped, the running plugin streams the gripper joint with
`valid = false` so consumers can hold it instead of executing garbage.

## Calibration file

Plain text, one joint per line (`#` comments allowed):

```
# name  motor_id  feedback_id  model  sign  offset_rad
joint1  1  17  4340P   1  0.0
joint2  2  18  4340P   1  0.0
joint3  3  19  4340P   1  0.0
joint4  4  20  4310    1  0.0
joint5  5  21  4310    1  0.0
joint6  6  22  4310    1  0.0
gripper 7  23  4310    1  0.0
```

- `motor_id` / `feedback_id`: the motor's command (ESC) and feedback (MST) CAN ids, decimal.
  Factory reBot DevArm ids are `1..7` / `0x11..0x17` (17..23) — the defaults, so a calibration
  file is only needed for a sign flip, a zero offset, or a re-flashed id layout.
- `model`: Damiao model name (`4310`, `4310P`, `4340`, `4340P`) selecting the feedback
  fixed-point limits.
- `sign`: `-1` for any joint that moves opposite the URDF convention.
- `offset_rad`: feedback position at the joint's URDF zero pose. With the vendor's zeroing
  procedure (motors zeroed at the reference pose) this stays `0.0`.

## Joint order and names

The DOF order matches the `reBot-DevArm_fixend` URDF: `joint1 … joint6`, then `gripper` (the 7th
Damiao motor). Downstream consumers read joints **by name** from the `JointStateOutput`, so wire
order does not matter.

## Consume in Python

```python
from isaacteleop.retargeting_engine.deviceio_source_nodes import JointStateSource

source = JointStateSource(
    name="leader",
    collection_id="rebot_devarm_leader",
    joint_names=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper"],
)
```

Pair it with a `JointStateRetargeter` for joint-space or EE-space teleoperation, exactly like the
SO-101 leader (`src/plugins/so101_leader`).
