<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SO-101 Robot Arm Plugin

Teleoperation plugin for the SO-101 6-DOF robot arm (leader arm). Reads joint
positions from Feetech STS3215 serial bus servos and pushes normalized data via
OpenXR SchemaPusher for use as a teleoperation input device.

## Overview

The SO-101 is a 6-DOF robot arm (5 DOF articulated body + 1 DOF gripper) used
in a leader-follower teleoperation setup. This plugin reads the **leader arm**
and streams joint positions into the Isaac Teleop data pipeline.

### Joints

| Joint          | Servo ID | Description                   |
|----------------|----------|-------------------------------|
| shoulder_pan   | 1        | Base rotation (yaw)           |
| shoulder_lift  | 2        | Shoulder pitch                |
| elbow_flex     | 3        | Elbow pitch                   |
| wrist_flex     | 4        | Wrist pitch                   |
| wrist_roll     | 5        | Wrist rotation (roll)         |
| gripper        | 6        | Gripper open/close            |

## Hardware Requirements

- **SO-101 robot arm** (leader arm) — assembled and wired
- **6× Feetech STS3215** serial bus servos (pre-installed in SO-101 kit)
- **USB serial adapter** — the SO-101 control board connects via USB and
  appears as `/dev/ttyACM0` or `/dev/ttyUSB0`
- **Linux host** with USB port

### Assembly Reference

Follow the official SO-101 assembly guide. Ensure all 6 servos are connected
to the serial bus daisy chain and powered from the control board.

### Wiring

The STS3215 servos use a 3-wire serial bus (VCC, GND, DATA). All servos share
a single half-duplex UART line. The control board provides a USB-to-serial
bridge. No additional wiring is needed beyond the standard SO-101 assembly.

Servo IDs must be programmed 1-6 (factory default for the SO-101 kit).

## Environment Variables

| Variable              | Default         | Description                       |
|-----------------------|-----------------|-----------------------------------|
| `SO101_SERIAL_PORT`   | `/dev/ttyACM0`  | Serial port path                  |
| `SO101_BAUDRATE`      | `1000000`       | Serial baudrate                   |
| `SO101_COLLECTION_ID` | `so101_leader`  | OpenXR tensor collection ID       |

Command-line arguments override environment variables:

```bash
./so101_arm_plugin [port] [baudrate] [collection_id]
```

## Build

Build with the main Isaac Teleop project:

```bash
cmake -B build -DBUILD_PLUGINS=ON
cmake --build build --target so101_arm_plugin
```

The standalone printer tool is also built:

```bash
cmake --build build --target so101_printer
```

## Usage

### Plugin (with Isaac Teleop)

```bash
# Default: /dev/ttyACM0, 1000000 baud
./build/src/plugins/so101/so101_arm_plugin

# Custom port
SO101_SERIAL_PORT=/dev/ttyUSB0 ./build/src/plugins/so101/so101_arm_plugin

# Command-line override
./build/src/plugins/so101/so101_arm_plugin /dev/ttyUSB0 1000000 so101_leader
```

### Printer Tool (standalone diagnostics)

The printer reads raw servo positions without OpenXR, useful for verifying
hardware connectivity:

```bash
./build/src/plugins/so101/tools/so101_printer

# Custom port
./build/src/plugins/so101/tools/so101_printer /dev/ttyUSB0
```

Output (continuously updated, ~30 Hz):
```
shoulder_pan  :  2048  |  shoulder_lift :  1500  |  elbow_flex   :  2200  |  wrist_flex   :  2048  |  wrist_roll   :  2048  |  gripper      :  1024
```

## Calibration

Joint positions are normalized to `[-1.0, 1.0]` centered on a calibration
midpoint (default 2048 for all joints). The normalization formula:

```
normalized = (raw - center) / max(center, 4095 - center)
```

This ensures the full [-1, 1] range maps to the full servo travel regardless
of where the center is placed.

**To calibrate:** Move the arm to its neutral/home position and record the raw
values using the printer tool. Future versions will support a calibration file
or environment variable for per-joint center overrides.

## Troubleshooting

### Permission denied on serial port

Add your user to the `dialout` group:
```bash
sudo usermod -aG dialout $USER
# Log out and back in for the change to take effect
```

Or set a udev rule for the SO-101:
```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0666"' | sudo tee /etc/udev/rules.d/99-so101.rules
sudo udevadm control --reload-rules
```

### No response from servos

1. Verify the USB cable is connected and the control board LED is on
2. Check the port exists: `ls /dev/ttyACM* /dev/ttyUSB*`
3. Verify baudrate matches (default 1000000 for STS3215)
4. Use the printer tool to test basic communication
5. Check that servo IDs are 1-6 (use the Feetech debug software to verify)

### Intermittent read failures

- Ensure the power supply can handle all 6 servos simultaneously
- Check for loose connections on the serial bus daisy chain
- Reduce baudrate to 500000 if the USB adapter doesn't support 1Mbaud reliably

### Serial port path changed

The port path (`/dev/ttyACM0`) can change if other USB devices are
connected. Use udev rules to create a stable symlink:

```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", SYMLINK+="so101"' | sudo tee /etc/udev/rules.d/99-so101.rules
sudo udevadm control --reload-rules
```

Then use `SO101_SERIAL_PORT=/dev/so101`.

## Data Format

The plugin pushes `SO101ArmOutput` FlatBuffers via OpenXR at 90 Hz:

```fbs
table SO101ArmOutput {
  shoulder_pan: float;    // [-1.0, 1.0]
  shoulder_lift: float;   // [-1.0, 1.0]
  elbow_flex: float;      // [-1.0, 1.0]
  wrist_flex: float;      // [-1.0, 1.0]
  wrist_roll: float;      // [-1.0, 1.0]
  gripper: float;         // [-1.0, 1.0] (0.0 = open, 1.0 = closed after mapping)
}
```
