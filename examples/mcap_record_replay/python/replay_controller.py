# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Replay a recorded controller-tracking MCAP file and visualize it with viser.

``mode=SessionMode.REPLAY`` skips all OpenXR initialization, so this runs
headless on any machine. Open the URL viser prints (default
http://localhost:8080) in a browser to see aim/grip points + a per-controller
HUD (thumbstick, trigger, squeeze, buttons).

Usage:
    python replay_controller.py [path/to/file.mcap] [--port 8080] [--loop]

If no path is given, the newest file under ``../recordings/`` is used.
``--loop`` keeps replaying the file end-to-end until the process is killed.

See: https://nvidia.github.io/IsaacTeleop/main/references/mcap_record_replay.html
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import viser
from mcap.reader import make_reader

from isaacteleop.deviceio import McapReplayConfig
from isaacteleop.retargeting_engine.tensor_types.indices import ControllerInputIndex
from isaacteleop.teleop_session_manager import (
    SessionMode,
    TeleopSession,
    TeleopSessionConfig,
)

from common import build_controller_pipeline


def mcap_duration_s(path: Path) -> float:
    """Read MCAP summary statistics and return wall-clock duration in seconds.

    The C++ replay session does not signal end-of-file — it just logs
    ``Replay*TrackerImpl: ... data not found`` and keeps spinning. We use
    this duration as the stop condition so playback exits cleanly.
    """
    with open(path, "rb") as f:
        reader = make_reader(f)
        summary = reader.get_summary()
        if summary is None or summary.statistics is None:
            raise RuntimeError(f"{path}: MCAP file has no summary/statistics block")
        stats = summary.statistics
        if stats.message_count == 0:
            return 0.0
        return (stats.message_end_time - stats.message_start_time) / 1e9


LEFT_COLOR = (0.25, 0.85, 0.35)
RIGHT_COLOR = (0.35, 0.55, 0.95)
INVALID_COLOR = (1.0, 0.0, 0.0)


def resolve_mcap(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        if not path.exists():
            sys.exit(f"[replay] error: {path} does not exist")
        return path

    recordings = Path(__file__).resolve().parent.parent / "recordings"
    candidates = list(recordings.glob("*.mcap"))
    if not candidates:
        sys.exit(
            f"[replay] error: no .mcap files in {recordings}. "
            "Run record_controller.py first or pass a path."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _segment(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    return np.stack([start, end], axis=0).astype(np.float32)


class ControllerViz:
    """Per-controller viser handles (3D pose + live input-state HUD)."""

    def __init__(
        self,
        server: viser.ViserServer,
        name: str,
        color: tuple[float, float, float],
    ):
        self.color = np.array(color, dtype=np.float32)
        zero_pt = np.zeros((1, 3), dtype=np.float32)
        zero_seg = np.zeros((0, 2, 3), dtype=np.float32)
        zero_seg_colors = np.zeros((0, 2, 3), dtype=np.float32)

        self.aim = server.scene.add_point_cloud(
            name=f"/{name}/aim",
            points=zero_pt,
            colors=np.tile(self.color, (1, 1)),
            point_size=0.015,
        )
        self.grip = server.scene.add_point_cloud(
            name=f"/{name}/grip",
            points=zero_pt,
            colors=np.tile(self.color, (1, 1)),
            point_size=0.015,
        )
        self.ray = server.scene.add_line_segments(
            name=f"/{name}/ray",
            points=zero_seg,
            colors=zero_seg_colors,
            line_width=2.0,
        )

        with server.gui.add_folder(name):
            self.hud_tracking = server.gui.add_checkbox("tracked", False, disabled=True)
            self.hud_aim_valid = server.gui.add_checkbox(
                "aim_valid", False, disabled=True
            )
            self.hud_grip_valid = server.gui.add_checkbox(
                "grip_valid", False, disabled=True
            )
            self.hud_stick = server.gui.add_vector2(
                "thumbstick_xy",
                initial_value=(0.0, 0.0),
                min=(-1.0, -1.0),
                max=(1.0, 1.0),
                disabled=True,
            )
            self.hud_trigger_value = server.gui.add_number(
                "trigger",
                initial_value=0.0,
                min=0.0,
                max=1.0,
                step=0.01,
                disabled=True,
            )
            self.hud_trigger = server.gui.add_progress_bar(0.0)
            self.hud_squeeze_value = server.gui.add_number(
                "squeeze",
                initial_value=0.0,
                min=0.0,
                max=1.0,
                step=0.01,
                disabled=True,
            )
            self.hud_squeeze = server.gui.add_progress_bar(0.0)
            self.hud_primary = server.gui.add_checkbox(
                "primary_click", False, disabled=True
            )
            self.hud_secondary = server.gui.add_checkbox(
                "secondary_click", False, disabled=True
            )
            self.hud_stick_click = server.gui.add_checkbox(
                "thumbstick_click", False, disabled=True
            )
            self.hud_menu_click = server.gui.add_checkbox(
                "menu_click", False, disabled=True
            )

    def update(self, state: dict) -> None:
        aim_valid: bool = state["aim_valid"]
        grip_valid: bool = state["grip_valid"]
        aim_pos: np.ndarray | None = state["aim_pos"]
        grip_pos: np.ndarray | None = state["grip_pos"]

        self.hud_tracking.value = state["tracked"]
        self.hud_aim_valid.value = aim_valid
        self.hud_grip_valid.value = grip_valid
        self.hud_stick.value = state["thumbstick_xy"]
        self.hud_trigger.value = max(0.0, min(1.0, state["trigger"]))
        self.hud_trigger_value.value = state["trigger"]
        self.hud_squeeze.value = max(0.0, min(1.0, state["squeeze"]))
        self.hud_squeeze_value.value = state["squeeze"]
        self.hud_primary.value = state["primary_click"]
        self.hud_secondary.value = state["secondary_click"]
        self.hud_stick_click.value = state["thumbstick_click"]
        self.hud_menu_click.value = state["menu_click"]

        if aim_valid and aim_pos is not None:
            self.aim.points = aim_pos.reshape(1, 3).astype(np.float32)
            self.aim.colors = np.tile(self.color, (1, 1))
        else:
            self.aim.points = np.zeros((1, 3), dtype=np.float32)
            self.aim.colors = np.tile(INVALID_COLOR, (1, 1))

        if grip_valid and grip_pos is not None:
            self.grip.points = grip_pos.reshape(1, 3).astype(np.float32)
            self.grip.colors = np.tile(self.color, (1, 1))
        else:
            self.grip.points = np.zeros((1, 3), dtype=np.float32)
            self.grip.colors = np.tile(INVALID_COLOR, (1, 1))

        if aim_valid and grip_valid and aim_pos is not None and grip_pos is not None:
            seg = _segment(grip_pos, aim_pos).reshape(1, 2, 3)
            self.ray.points = seg
            self.ray.colors = np.tile(self.color, (1, 2, 1))
        else:
            self.ray.points = np.zeros((0, 2, 3), dtype=np.float32)
            self.ray.colors = np.zeros((0, 2, 3), dtype=np.float32)


def _controller_state(controller):
    if controller.is_none:
        return {
            "aim_pos": None,
            "grip_pos": None,
            "aim_valid": False,
            "grip_valid": False,
            "trigger": 0.0,
            "squeeze": 0.0,
            "thumbstick_xy": (0.0, 0.0),
            "primary_click": False,
            "secondary_click": False,
            "thumbstick_click": False,
            "menu_click": False,
            "tracked": False,
        }

    aim_valid = bool(controller[ControllerInputIndex.AIM_IS_VALID])
    grip_valid = bool(controller[ControllerInputIndex.GRIP_IS_VALID])
    return {
        "aim_pos": np.asarray(
            controller[ControllerInputIndex.AIM_POSITION], dtype=np.float32
        ),
        "grip_pos": np.asarray(
            controller[ControllerInputIndex.GRIP_POSITION], dtype=np.float32
        ),
        "aim_valid": aim_valid,
        "grip_valid": grip_valid,
        "trigger": float(controller[ControllerInputIndex.TRIGGER_VALUE]),
        "squeeze": float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
        "thumbstick_xy": (
            float(controller[ControllerInputIndex.THUMBSTICK_X]),
            float(controller[ControllerInputIndex.THUMBSTICK_Y]),
        ),
        "primary_click": float(controller[ControllerInputIndex.PRIMARY_CLICK]) > 0.5,
        "secondary_click": float(controller[ControllerInputIndex.SECONDARY_CLICK])
        > 0.5,
        "thumbstick_click": float(controller[ControllerInputIndex.THUMBSTICK_CLICK])
        > 0.5,
        "menu_click": float(controller[ControllerInputIndex.MENU_CLICK]) > 0.5,
        "tracked": aim_valid or grip_valid,
    }


def run_once(
    mcap_path: Path,
    duration_s: float,
    viz_left: ControllerViz,
    viz_right: ControllerViz,
) -> int:
    """Play the file once for ``duration_s`` wall-clock seconds. Returns frame count."""
    config = TeleopSessionConfig(
        app_name="McapControllerReplayExample",
        pipeline=build_controller_pipeline(),
        mode=SessionMode.REPLAY,
        mcap_config=McapReplayConfig(str(mcap_path)),
    )

    frames = 0
    with TeleopSession(config) as session:
        start = time.time()
        while time.time() - start < duration_s:
            result = session.step()
            left = result["controller_left"]
            right = result["controller_right"]

            l_state = _controller_state(left)
            r_state = _controller_state(right)

            viz_left.update(l_state)
            viz_right.update(r_state)

            frames = session.frame_count
            if frames % 60 == 0:
                print(
                    f"[replay] t={time.time() - start:5.2f}s  "
                    f"frame={frames}  "
                    f"L={'Y' if l_state['aim_valid'] else '-'} "
                    f"R={'Y' if r_state['aim_valid'] else '-'}"
                )
            time.sleep(1 / 60)
    print(f"[replay] reached end of recording after {frames} frames")
    return frames


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mcap", nargs="?", help="Path to .mcap file")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Viser HTTP bind address (default: 127.0.0.1; pass 0.0.0.0 to expose externally)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Viser HTTP port")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Replay the file in a loop until Ctrl+C",
    )
    args = parser.parse_args(argv[1:])

    mcap_path = resolve_mcap(args.mcap)
    duration_s = mcap_duration_s(mcap_path)

    server = viser.ViserServer(host=args.host, port=args.port)
    server.scene.set_up_direction("+y")
    server.scene.add_grid(name="/grid", width=2.0, height=2.0, cell_size=0.1)

    viz_left = ControllerViz(server, "controller_left", LEFT_COLOR)
    viz_right = ControllerViz(server, "controller_right", RIGHT_COLOR)

    print(f"[replay] viser running at http://localhost:{args.port}")
    print(f"[replay] reading {mcap_path} (duration {duration_s:.2f}s)")

    while True:
        run_once(mcap_path, duration_s, viz_left, viz_right)
        if not args.loop:
            break
        print("[replay] looping…")

    print("[replay] done — viser server still up; Ctrl+C to exit")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
