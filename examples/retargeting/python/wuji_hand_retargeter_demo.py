#!/usr/bin/env python3
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

      Recordings come from the wuji-retargeting example tooling
      (https://github.com/wuji-technology/wuji-retargeting): each of its
      example input devices (Wuji glove, Apple Vision Pro, Intel RealSense,
      MP4 video) emits this frame format, its teleop examples record it with
      their input-data logging option, and ``example/calibrate_offset.py
      --dump-pkl`` records live glove takes. Keypoints are the 21 MediaPipe
      hand landmarks (wrist; thumb CMC/MCP/IP/TIP; index, middle, ring,
      pinky MCP/PIP/DIP/TIP), wrist-relative positions in meters.

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
    python wuji_hand_retargeter_demo.py --mode replay --replay my_take.pkl
    python wuji_hand_retargeter_demo.py --mode drive
"""

import argparse
import contextlib
import math
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


class _ReplayUnpickler(pickle.Unpickler):
    """Unpickler restricted to what the replay frame format needs.

    Plain ``pickle.load`` executes arbitrary code embedded in the file, and a
    recording may have been produced elsewhere or shared.
    """

    _ALLOWED = {
        ("numpy", "ndarray"),
        ("numpy", "dtype"),
        ("numpy.core.multiarray", "_reconstruct"),  # numpy < 2
        ("numpy._core.multiarray", "_reconstruct"),  # numpy >= 2
    }

    def find_class(self, module: str, name: str):
        if (module, name) not in self._ALLOWED:
            raise pickle.UnpicklingError(
                f"{module}.{name} is not allowed in a replay recording"
            )
        return super().find_class(module, name)


def run_replay(model: str, hand_side: str, path: str, loop: bool) -> int:
    print(f"[mode] replay {path} (device-free)\n")
    retargeter = _build_retargeter(model, hand_side)
    with open(path, "rb") as fh:
        frames = _ReplayUnpickler(fh).load()
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


class _CommandLowPass:
    """Single-pole low-pass over the joint-command stream.

    Wuji Hand 1 gets SDK-side smoothing via ``realtime_controller(LowPass(...))``,
    but Hand 2's MIT-mode ``joint_command`` stream has no SDK filter, so the demo
    applies the same 5 Hz cutoff here before publishing.
    """

    def __init__(self, cutoff_hz: float) -> None:
        self._cutoff_hz = cutoff_hz
        self._state = None
        self._last_update_s = None

    def __call__(self, command: list) -> list:
        now = time.monotonic()
        target = np.asarray(command, dtype=np.float64)
        if self._state is None:
            self._state = target.copy()
        else:
            omega_dt = 2.0 * math.pi * self._cutoff_hz * (now - self._last_update_s)
            alpha = omega_dt / (1.0 + omega_dt)
            self._state += alpha * (target - self._state)
        self._last_update_s = now
        return self._state.tolist()


def run_drive(
    model: str | None,
    hand_side: str,
    plugin_path: str | None = None,
    hand_sn: str | None = None,
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

    # A left glove driving a right hand (or vice versa) mirrors silently, so
    # flag a side mismatch between --hand and the connected hand up front.
    # Wuji Hand 2's handedness resource returns 'left'/'right'; anything else
    # (older firmware, Hand 1's integer encoding) skips the check quietly.
    try:
        device_side = str(hand.handedness().get()).strip().lower()
    except Exception:
        device_side = ""
    if device_side in ("left", "right") and device_side != hand_side:
        print(
            f"WARNING: --hand {hand_side} but the connected hand reports "
            f"'{device_side}'; motion will be mirrored."
        )

    # The retarget model must match the connected hardware, so drive mode
    # derives it from the detected hand — and rejects a conflicting explicit
    # --model instead of silently overriding it.
    detected_model = "wuji_hand_2" if is_hand2 else "wuji_hand"
    if model is not None and model != detected_model:
        print(
            f"--model {model} does not match the connected hand "
            f"({detected_model}); drop --model or pass {detected_model}."
        )
        manager.disconnect_all()
        return 1
    model = detected_model

    # Vendor-recommended safe defaults for this demo. effort_limit is the
    # per-joint current limit in amperes (the SDK's Kt=1.0 placeholder makes
    # effort in N·m numerically equal to current in A until the real Kt
    # lands); mit_params is the MIT impedance controller's (kp, kd) pair.
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
    pipeline = OutputCombiner(
        {
            "hand_joints": connected.output("hand_joints"),
            "hand_valid": connected.output("hand_valid"),
        }
    )

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
        last_command = None

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
                    command = list(result["hand_joints"])  # 20 values, firmware order
                    # Forwarding the retargeter's zeros on a tracking dropout
                    # would snap a mid-grasp hand to zero, so hold the last
                    # valid command while hand_valid reports the dropout.
                    if float(result["hand_valid"][0]) > 0.5:
                        last_command = command
                    else:
                        command = last_command
                    if command is not None:
                        send(command)
                    dt = time.monotonic() - t0
                    if dt < budget:
                        time.sleep(budget - dt)
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)

    try:
        hand.enable()
        if is_hand2:
            publisher = hand.joint_command().publish()
            # Same 5 Hz cutoff as the Hand 1 path below; see _CommandLowPass.
            smooth = _CommandLowPass(cutoff_hz=5.0)
            loop(
                lambda q: publisher.send([JointCommand(p, 0.0, 0.0) for p in smooth(q)])
            )
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
        "--model",
        default=None,
        choices=["wuji_hand", "wuji_hand_2"],
        help="Retarget model. synthetic/replay: defaults to wuji_hand_2. "
        "drive: auto-detected from the connected hand; a conflicting explicit "
        "value is an error.",
    )
    parser.add_argument(
        "--hand",
        default="right",
        choices=["left", "right"],
        help="Hand side to retarget. drive mode warns when this does not "
        "match the connected hand's reported handedness.",
    )
    parser.add_argument(
        "--replay",
        metavar="PKL",
        default=None,
        help="Recorded keypoints (.pkl) for --mode replay: a pickled list of "
        '{"left_fingers": (21,3), "right_fingers": (21,3)} frames in MediaPipe '
        "21-landmark order (wrist-relative, meters), as produced by the "
        "wuji-retargeting example tooling (calibrate_offset.py --dump-pkl).",
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
    # Device-free modes have no hardware to detect the model from.
    model = args.model or "wuji_hand_2"
    if args.mode == "replay":
        if not args.replay:
            parser.error("--mode replay requires --replay FILE.pkl")
        return run_replay(model, args.hand, args.replay, args.loop)
    return run_synthetic(model, args.hand)


if __name__ == "__main__":
    sys.exit(main())
