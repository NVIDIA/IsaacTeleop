#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""List connected cameras (OAK-D, ZED, and V4L2)."""

from pathlib import Path


def list_oakd_cameras():
    """List OAK-D cameras using DepthAI SDK v3."""
    print("\n=== OAK-D Cameras (DepthAI) ===")
    try:
        import depthai as dai

        devices = dai.Device.getAllAvailableDevices()
        if not devices:
            print("  No OAK-D cameras found")
        else:
            for dev in devices:
                # depthai 3.x uses deviceId attribute
                device_id = getattr(
                    dev, "deviceId", getattr(dev, "getMxId", lambda: "unknown")()
                )
                state = getattr(dev, "state", None)
                state_str = state.name if state else "unknown"
                print(f"  DeviceId: {device_id}  State: {state_str}")
    except ImportError:
        print("  depthai not installed")
    except Exception as e:
        print(f"  Error: {e}")


def list_zed_cameras():
    """List ZED cameras using ZED SDK."""
    print("\n=== ZED Cameras ===")
    try:
        import pyzed.sl as sl

        devices = sl.Camera.get_device_list()
        if not devices:
            print("  No ZED cameras found")
        else:
            for dev in devices:
                print(
                    f"  Serial: {dev.serial_number}  "
                    f"Model: {dev.camera_model.name}  "
                    f"State: {dev.camera_state.name}"
                )
    except ImportError:
        print("  pyzed not installed")
    except Exception as e:
        print(f"  Error: {e}")


def list_v4l2_cameras():
    """List V4L2 video devices with supported formats, resolutions, and frame rates."""
    import subprocess

    print("\n=== V4L2 Cameras ===")
    try:
        v4l2_dir = Path("/sys/class/video4linux")
        if not v4l2_dir.exists():
            print("  No V4L2 subsystem found")
            return

        devices = sorted(v4l2_dir.iterdir())
        if not devices:
            print("  No V4L2 devices found")
            return

        for dev in devices:
            dev_path = f"/dev/{dev.name}"
            name_file = dev / "name"
            name = name_file.read_text().strip() if name_file.exists() else "unknown"
            print(f"\n  {dev_path}  Name: {name}")

            try:
                result = subprocess.run(
                    ["v4l2-ctl", "-d", dev_path, "--list-formats-ext"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if not line or line.startswith("ioctl") or line.startswith("Type"):
                            continue
                        print(f"    {line}")
            except FileNotFoundError:
                print("    (install v4l-utils for format details)")
            except subprocess.TimeoutExpired:
                print("    (timeout querying formats)")
    except Exception as e:
        print(f"  Error: {e}")


def main():
    list_oakd_cameras()
    list_zed_cameras()
    list_v4l2_cameras()
    print()


if __name__ == "__main__":
    main()
