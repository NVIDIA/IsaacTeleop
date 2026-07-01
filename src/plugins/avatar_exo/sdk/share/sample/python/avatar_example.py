"""Minimal Avatar SDK RAW stream example.

Set AVATAR_DIST_PREFIX to a deb staging root for local testing:
  export AVATAR_DIST_PREFIX=/path/to/avatar-sdk_x.y.z_amd64
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import time
from pathlib import Path

_dist_root = os.environ.get("AVATAR_DIST_PREFIX")
SDK_PREFIX = Path(_dist_root) / "opt/avatar-sdk" if _dist_root else Path("/opt/avatar-sdk")
if "AVATAR_SDK_DEV_BUILD_DIR" not in os.environ:
    sys.path.insert(0, str(SDK_PREFIX / "lib/python"))

from avatar_sdk import AvatarSDK, DeviceDataCategery, DeviceSide, DeviceType, ErrorCode

_FINGER_GROUPS: list[tuple[str, int]] = [
    ("Thumb", 5),
    ("Index", 4),
    ("Middle", 4),
    ("Ring", 4),
    ("Pinky", 5),
]
_LEGACY_PINKY_JOINTS = 3
_RAW_LINE_PAD = 160

RUNNING = True


def _on_signal(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def _raw_groups(pos: list[float]) -> list[tuple[str, list[float]]]:
    groups: list[tuple[str, list[float]]] = []
    idx = 0
    for name, n in _FINGER_GROUPS:
        remaining = len(pos) - idx
        if name == "Pinky" and remaining == _LEGACY_PINKY_JOINTS:
            n = _LEGACY_PINKY_JOINTS
        if remaining < n:
            break
        groups.append((name, pos[idx : idx + n]))
        idx += n
    return groups


def format_raw_line(pos: list[float]) -> str:
    """Format SDK RAW radians as degrees so the stream is easy to inspect."""
    parts = [
        f"{name}:{','.join(f'{math.degrees(value):.1f}°' for value in values)}"
        for name, values in _raw_groups(pos)
    ]
    line = " | ".join(parts)
    if len(line) < _RAW_LINE_PAD:
        line += " " * (_RAW_LINE_PAD - len(line))
    return line


def _load_config_text(config_arg: str | None) -> tuple[Path, str]:
    cfg_path = Path(config_arg) if config_arg else SDK_PREFIX / "share/sdk_config.json"
    if not cfg_path.is_file():
        return cfg_path, "{}"

    cfg_path = cfg_path.resolve()
    os.environ.setdefault("AVATAR_SDK_CONFIG_PATH", str(cfg_path))
    os.environ.setdefault("AVATAR_SDK_CONFIG_DIR", str(cfg_path.parent))
    os.environ.setdefault("AVATAR_SDK_HAND_FK_DATA_DIR", str(cfg_path.parent / "hand_fk"))
    return cfg_path, cfg_path.read_text(encoding="utf-8")


def _requested_sides(side_arg: str) -> list[tuple[str, DeviceSide]]:
    if side_arg == "BOTH":
        return [("LEFT", DeviceSide.LEFT), ("RIGHT", DeviceSide.RIGHT)]
    if side_arg == "LEFT":
        return [("LEFT", DeviceSide.LEFT)]
    return [("RIGHT", DeviceSide.RIGHT)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Avatar SDK Python RAW stream example")
    parser.add_argument("config", nargs="?", default=None, help="SDK config json path")
    parser.add_argument("--side", choices=("LEFT", "RIGHT", "BOTH"), default="BOTH", help="Glove side to connect")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _on_signal)

    cfg_path, config_json = _load_config_text(args.config)

    print(f"Avatar Example - Starting (config: {cfg_path if cfg_path.is_file() else args.config})")
    sdk = AvatarSDK.get_instance()
    ec = sdk.initialize(config_json)
    if ec != ErrorCode.SUCCESS:
        print(f"Error: initialize failed ({ec})", file=sys.stderr)
        return 1

    try:
        print("Waiting for device discovery...")
        time.sleep(2.0)

        devices = sdk.list_device_info()
        print(f"Discovered {len(devices)} device(s):")
        for d in devices:
            print(f"  sn={d.sn}  side={d.device_side}  online={d.online}")

        gloves: list[tuple[str, object]] = []
        for label, dev_side in _requested_sides(args.side):
            glove = sdk.get_device(DeviceType.GLOVE, dev_side)
            if glove is None:
                print(f"Warning: no {label} glove found", file=sys.stderr)
                continue
            # Retargeting is not needed for this RAW validation sample.
            glove.init('{"enable_retarget": false, "enable_identity_query": false}')
            glove.start()
            gloves.append((label, glove))

        if not gloves:
            print("Error: no glove(s) connected", file=sys.stderr)
            return 1

        print("Avatar Example - Streaming RAW data in degrees (Ctrl+C to stop)")

        while RUNNING:
            lines: list[str] = []
            for label, glove in gloves:
                ec_fetch, frame = glove.fetch_data(DeviceDataCategery.RAW)
                if ec_fetch != ErrorCode.SUCCESS or frame is None:
                    continue
                pos = list(frame.raw.joint.position)
                lines.append(f"[{label}] {format_raw_line(pos)}")
            if lines:
                print("\r" + "  ".join(lines), end="", flush=True)
            time.sleep(0.1)

        print("\nAvatar Example - Stopping")
        for _, glove in gloves:
            glove.stop()
        return 0
    finally:
        sdk.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
