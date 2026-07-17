# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Wuji Hand Retargeter Demo.

Maps hand keypoints to Wuji hand joint angles via ``WujiHandRetargeter``. Three
modes — the first two are device-free (and headless / CI-friendly), the third
drives real hardware:

  --mode synthetic (default)
      A synthetic open-hand pose -> retarget -> print the 20 joint angles.
      No input device, no headset.

  --mode replay --replay FILE.pkl
      Replay recorded MediaPipe keypoints from a pickled list of
      ``{"left_fingers": (21,3)|None, "right_fingers": (21,3)|None}`` mappings
      -> retarget -> print.

  --mode drive
      HARDWARE. Runs the full Isaac Teleop pipeline (``HandsSource`` ->
      ``WujiHandRetargeter`` inside a ``TeleopSession``) and drives a real
      Wuji Hand / Wuji Hand 2 via ``wuji_sdk``. Requires an OpenXR hand-tracking
      source on the runtime (the Wuji glove plugin or a Quest) AND a real
      Wuji Hand reachable via wuji_sdk on the same LAN.

A retargeter is device-agnostic; the device binding lives only in the opt-in
``drive`` mode, whose hardware/session imports are loaded lazily so the
device-free modes run without them.

Prereqs:
    pip install 'isaacteleop[wuji]'    # brings in wuji-sdk[retarget]

Usage:
    python wuji_hand_retargeter_demo.py
    python wuji_hand_retargeter_demo.py --mode replay --replay data/avp1.pkl
    python wuji_hand_retargeter_demo.py --mode drive
"""

import argparse
import contextlib
import pickle
import signal
import sys
import time

import numpy as np

from isaacteleop.retargeters import WujiHandRetargeter, WujiHandRetargeterConfig
from isaacteleop.retargeters.wuji_hand_retargeter import OPENXR_TO_MEDIAPIPE_INDICES
from isaacteleop.retargeting_engine.interface import TensorGroup
from isaacteleop.retargeting_engine.tensor_types import (
    HandInput,
    HandInputIndex,
    NUM_HAND_JOINTS,
)

_FINGERS = ("thumb", "index", "middle", "ring", "pinky")
_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

FPS = 120  # drive-mode loop-rate ceiling


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_open_hand_keypoints() -> np.ndarray:
    """A synthetic open-right-hand pose, (21, 3) in meters, MediaPipe order."""
    kp = np.zeros((21, 3), dtype=np.float32)
    for base, x in [(1, -0.04), (5, -0.03), (9, -0.01), (13, 0.01), (17, 0.03)]:
        for k in range(4):
            kp[base + k] = [x, 0.03 * (k + 1), 0.0]
    kp[1] = [-0.03, 0.02, 0.01]  # thumb CMC nearer the palm
    return kp


def keypoints_to_hand_input(kp21: np.ndarray) -> TensorGroup:
    """Lift (21,3) MediaPipe keypoints into a 26-joint OpenXR ``HandInput``."""
    tg = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    valid = np.zeros(NUM_HAND_JOINTS, dtype=np.uint8)
    # Shared with the retargeter: entry mp_idx holds the OpenXR joint index, so the
    # same table scatters MediaPipe -> OpenXR here and gathers back in the retargeter.
    for mp_idx, xr_idx in enumerate(OPENXR_TO_MEDIAPIPE_INDICES):
        positions[xr_idx] = kp21[mp_idx]
        valid[xr_idx] = 1
    tg[HandInputIndex.JOINT_POSITIONS] = positions
    tg[HandInputIndex.JOINT_ORIENTATIONS] = np.tile(_ID_QUAT, (NUM_HAND_JOINTS, 1))
    tg[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32) * 0.01
    tg[HandInputIndex.JOINT_VALID] = valid
    return tg


def _print_command(qpos) -> None:
    for f, name in enumerate(_FINGERS):
        joints = qpos[f * 4 : (f + 1) * 4]
        print(f"  {name:6s}: {[f'{v:+.3f}' for v in joints]}")


def _retarget(retargeter, hand_side: str, kp21: np.ndarray) -> list:
    outputs = retargeter({f"hand_{hand_side}": keypoints_to_hand_input(kp21)})
    return [float(outputs["hand_joints"][i]) for i in range(20)]


def _build_retargeter(model: str, hand_side: str):
    print(f"  building RetargetSession (model={model}, hand={hand_side})...")
    return WujiHandRetargeter(
        WujiHandRetargeterConfig(model=model, hand_side=hand_side), name="wuji_demo"
    )


# ---------------------------------------------------------------------------
# Device-free modes
# ---------------------------------------------------------------------------


def run_synthetic(model: str, hand_side: str) -> int:
    print("[mode] synthetic open hand (device-free)\n")
    retargeter = _build_retargeter(model, hand_side)
    qpos = _retarget(retargeter, hand_side, make_open_hand_keypoints())
    if not all(np.isfinite(qpos)):
        print("FAIL: non-finite output")
        return 1
    print("\njoint command (radians, finger-major):")
    _print_command(qpos)
    print("\nOK: 20 DOFs, all finite.")
    return 0


def run_replay(model: str, hand_side: str, path: str, loop: bool) -> int:
    print(f"[mode] replay {path} (device-free)\n")
    retargeter = _build_retargeter(model, hand_side)
    # Only load trusted, self-generated files: pickle can execute code while loading.
    with open(path, "rb") as fh:
        frames = pickle.load(fh)
    key = f"{hand_side}_fingers"
    n = 0
    t0 = time.time()
    while True:
        for frame in frames:
            kp = frame.get(key) if isinstance(frame, dict) else None
            if kp is None or np.allclose(kp, 0):
                continue
            qpos = _retarget(retargeter, hand_side, np.asarray(kp, dtype=np.float32))
            n += 1
            if n % 100 == 0:
                fps = n / (time.time() - t0)
                print(
                    f"  frame {n:5d}  fps={fps:5.1f}  thumb={[f'{v:+.2f}' for v in qpos[:4]]}"
                )
        if not loop:
            break
    print(f"\nOK: replayed {n} frames.")
    return 0


# ---------------------------------------------------------------------------
# Hardware mode: drive a real Wuji hand through a TeleopSession
# ---------------------------------------------------------------------------


def run_drive(
    model: str,
    hand_side: str,
    plugin_path: "str | None" = None,
    hand_sn: "str | None" = None,
) -> int:
    # Lazy imports: only the drive path needs the session + wuji_sdk hardware API.
    from pathlib import Path

    from isaacteleop.retargeting_engine.deviceio_source_nodes import HandsSource
    from isaacteleop.retargeting_engine.interface import OutputCombiner
    from isaacteleop.teleop_session_manager import (
        PluginConfig,
        TeleopSession,
        TeleopSessionConfig,
    )
    from wuji_sdk import DeviceType, JointCommand, LowPass, SdkManager

    print("[mode] drive a real Wuji hand (HARDWARE)\n")

    # Select the hand from scan metadata before connecting.
    manager = SdkManager.instance()
    hand_dev = None
    for device in manager.scan():
        if hand_sn and device.sn != hand_sn:
            continue
        if device.device_type in (DeviceType.WujiHand2, DeviceType.WujiHand):
            hand_dev = device
            break
    if hand_dev is None:
        print("No Wuji Hand / Wuji Hand 2 found")
        manager.disconnect_all()
        return 1

    hand = manager.connect(sn=hand_dev.sn, device_name=hand_dev.sn)
    is_hand2 = hand_dev.device_type == DeviceType.WujiHand2

    # The retarget model must match the connected hardware.
    model = "wuji_hand_2" if is_hand2 else "wuji_hand"
    if is_hand2:
        hand.effort_limit().set(1.5)
        hand.mit_params().set((3.0, 0.05))
    else:
        hand.set_all_effort_limit(1.5)

    # Isaac Teleop pipeline: hand tracking -> WujiHandRetargeter -> "hand_joints".
    hands = HandsSource(name="hands")
    source_out = HandsSource.RIGHT if hand_side == "right" else HandsSource.LEFT
    retargeter = _build_retargeter(model, hand_side)
    connected = retargeter.connect({f"hand_{hand_side}": hands.output(source_out)})
    pipeline = OutputCombiner({"hand_joints": connected.output("hand_joints")})

    # With --plugin-path, TeleopSession auto-launches the wuji_glove plugin
    # (reads its plugin.yaml `command`) and tears it down on exit, so the
    # operator runs only this app. Without it, an OpenXR hand source (the
    # plugin started separately, or a headset) must already feed the runtime.
    plugins = []
    if plugin_path:
        plugins = [
            PluginConfig(
                plugin_name="wuji_glove_plugin",
                plugin_root_id="wuji_glove",
                search_paths=[Path(plugin_path)],
            )
        ]
    session_config = TeleopSessionConfig(
        app_name="WujiTeleopDrive", trackers=[], plugins=plugins, pipeline=pipeline
    )

    budget = 1.0 / FPS

    def loop(send):
        stop_requested = False

        def request_stop(_signum, _frame):
            nonlocal stop_requested
            stop_requested = True

        # Finish the current step before handling Ctrl+C so device cleanup completes.
        previous_sigint_handler = signal.signal(signal.SIGINT, request_stop)
        try:
            with TeleopSession(session_config) as session:
                print("Teleoperating (Ctrl+C to stop)...")
                while not stop_requested:
                    t0 = time.monotonic()
                    result = session.step()
                    send(list(result["hand_joints"]))  # 20 values, firmware order
                    dt = time.monotonic() - t0
                    if dt < budget:
                        time.sleep(budget - dt)
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)

    try:
        hand.enable()
        if is_hand2:
            publisher = hand.joint_command().publish()
            loop(lambda q: publisher.send([JointCommand(p, 0.0, 0.0) for p in q]))
        else:
            with hand.realtime_controller(LowPass(cutoff_hz=5.0)) as controller:
                loop(controller.set_target_position)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            hand.disable()
        manager.disconnect_all()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Wuji Hand Retargeter Demo")
    parser.add_argument(
        "--mode",
        default="synthetic",
        choices=["synthetic", "replay", "drive"],
        help="synthetic/replay are device-free; drive runs hardware (default: synthetic).",
    )
    parser.add_argument(
        "--model", default="wuji_hand_2", choices=["wuji_hand", "wuji_hand_2"]
    )
    parser.add_argument("--hand", default="right", choices=["left", "right"])
    parser.add_argument(
        "--replay",
        metavar="PKL",
        default=None,
        help="Recorded keypoints (.pkl) for --mode replay.",
    )
    parser.add_argument("--loop", action="store_true", help="Loop the replay.")
    parser.add_argument(
        "--plugin-path",
        metavar="DIR",
        default=None,
        help="drive: auto-launch the wuji_glove plugin from this plugins dir "
        "(the dir containing wuji_glove/plugin.yaml + the binary). Managed "
        "by TeleopSession. If omitted, an OpenXR hand source (the plugin "
        "started separately, or a headset) must already be running.",
    )
    parser.add_argument(
        "--hand-sn",
        metavar="SN",
        default=None,
        help="drive: select this Wuji hand by serial number; otherwise the demo "
        "auto-detects the first hand using DeviceType.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Wuji Hand Retargeter Demo")
    print("=" * 60)

    if args.mode == "drive":
        return run_drive(args.model, args.hand, args.plugin_path, args.hand_sn)
    if args.mode == "replay":
        if not args.replay:
            parser.error("--mode replay requires --replay FILE.pkl")
        return run_replay(args.model, args.hand, args.replay, args.loop)
    return run_synthetic(args.model, args.hand)


if __name__ == "__main__":
    sys.exit(main())
