<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SO-101 Leader Arm plugin

Streams the SO-101 (5-DOF arm + gripper) leader joint angles as a `JointStateOutput` FlatBuffer
over the OpenXR tensor transport, using the generic **joint-space device** path
(`JointStateTracker` / `JointStateSource` / `JointStateRetargeter`).

The SO-101 leader is 6 FEETECH STS3215 bus servos on a half-duplex TTL serial bus (the same
hardware [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100) and HuggingFace
LeRobot drive via the FEETECH SCServo SDK). `FeetechBus` (`feetech_bus.{hpp,cpp}`) speaks that
SMS/STS wire protocol directly — no SDK dependency — and implements just what a *leader* needs:
disable torque so the arm can be back-driven by hand, then read `Present_Position` (register 56,
4096 ticks / 360°) for all six servos in a **single SYNC READ** per frame (one bus round-trip, not
six — matching LeRobot's `sync_read`). Ticks are converted to radians with per-joint calibration.

When no serial device is given, the plugin falls back to a **synthetic** trajectory so the
device → tracker → retargeter pipeline runs with no hardware (CI and the headless example).

## Run

```bash
# Synthetic backend (no hardware):
./install/plugins/so101_leader/so101_leader_plugin

# Real SO-101 leader on a serial port (Linux), default collection id "so101_leader":
./install/plugins/so101_leader/so101_leader_plugin /dev/ttyACM0

# ... with a custom collection id and a calibration file:
./install/plugins/so101_leader/so101_leader_plugin /dev/ttyACM0 so101_leader so101_leader.calib
```

Args are positional: `[device_path] [collection_id] [calibration_file]`. The serial backend is
Linux/macOS only (POSIX `termios`); the STS bus runs at 1,000,000 bps by default.

### Generate a calibration file

The `calibrate` subcommand reads the live servo positions and writes a calibration file (it does
**not** need the OpenXR runtime):

```bash
# Hold the arm at its zero/home pose; this prompts, then averages a few sync reads:
./install/plugins/so101_leader/so101_leader_plugin calibrate /dev/ttyACM0 so101_leader.calib

# Omit the output path to just print the current ticks (a "dump" for inspection):
./install/plugins/so101_leader/so101_leader_plugin calibrate /dev/ttyACM0
```

It disables torque, prompts you to hold the zero pose, captures each servo's `home_ticks`, and
writes the file below (all `sign` default to `+1` — flip any inverted joint by hand afterward).
This mirrors LeRobot's `lerobot-calibrate` homing step.

### Hardware setup (per SO-ARM100 / LeRobot)

- Assemble the leader arm and **remove the gearbox gears** so the joints move freely and only the
  position encoders are used (the plugin disables torque on connect, but the leader is meant to be
  back-driven).
- Give each servo a unique id `1..6` on the bus and set them all to the same baud rate. Use the
  FEETECH tool (`FT_SCServo_Debug_Qt` on Ubuntu) or LeRobot's `lerobot-setup-motors` to do this.
- Make sure your user can access the serial device (e.g. add it to the `dialout` group).

### Calibration file (optional)

Whitespace-separated, one joint per line; `#` starts a comment. Columns:
`name  servo_id  sign(+1/-1)  home_ticks(0..4095)`. The conversion is
`angle [rad] = sign * (ticks - home_ticks) * 2π / 4096`.

```
# joint          id  sign  home_ticks
shoulder_pan      1   1     2048
shoulder_lift     2   1     2048
elbow_flex        3   1     2048
wrist_flex        4   1     2048
wrist_roll        5   1     2048
gripper           6   1     2048
```

Defaults (no file): ids `1..6` in DOF order, `sign +1`, `home_ticks 2048` (servo center). Set
`home_ticks` to each servo's raw `Present_Position` at the joint's URDF-zero pose, and `sign` to
`-1` for any joint whose servo turns opposite the URDF convention (LeRobot's `drive_mode`). For
**joint-mirror** mode the retargeter's per-joint `offset`/`sign`/`scale` can also absorb
calibration; for **EE (URDF FK)** mode the joint angles must already match the URDF, so set
`home_ticks`/`sign` here.

The consumer side creates a `JointStateTracker("so101_leader")` (via
`JointStateSource(name=..., collection_id="so101_leader", joint_names=[...])`) on the same
`collection_id`. See `examples/teleop/python/joint_space_device_example.py` for the retargeting
pipeline (joint-mirror and task-space EE modes).

DOF order / names: `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`.
