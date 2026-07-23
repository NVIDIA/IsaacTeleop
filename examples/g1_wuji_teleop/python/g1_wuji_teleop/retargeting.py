# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Adapter for the external official ``wuji-retargeting`` package."""

from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class HandRetargetStepResult:
    frame_index: int
    left_joint_positions: np.ndarray
    right_joint_positions: np.ndarray
    left_joint_names: tuple[str, ...] | None
    right_joint_names: tuple[str, ...] | None
    ok: bool
    error: str | None = None
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


def import_official_wuji_retargeter():
    if importlib.util.find_spec("wuji_retargeting.retarget") is None:
        raise ModuleNotFoundError(
            "Official wuji-retargeting is not installed in this Python environment. "
            "Install it with `python -m pip install -e /path/to/wuji-retargeting` "
            "before running the G1-Wuji teleop example."
        )

    from wuji_retargeting.retarget import Retargeter

    return Retargeter


def _as_float32_numpy(values: Any, shape: tuple[int, ...]) -> np.ndarray:
    return np.asarray(values, dtype=np.float32).reshape(shape)


def _valid_skeleton21(skeleton: np.ndarray) -> tuple[bool, str | None]:
    if skeleton.shape != (21, 3):
        return False, f"unexpected shape {skeleton.shape}"
    if not np.all(np.isfinite(skeleton)):
        return False, "non-finite landmarks"

    centered = skeleton - skeleton[0:1]
    if float(np.max(np.linalg.norm(centered, axis=1))) < 1.0e-4:
        return False, "all landmarks collapsed to the wrist"

    palm_vec_a = skeleton[5] - skeleton[0]
    palm_vec_b = skeleton[9] - skeleton[0]
    if np.linalg.norm(palm_vec_a) < 1.0e-5 or np.linalg.norm(palm_vec_b) < 1.0e-5:
        return False, "missing palm anchor landmarks"
    if np.linalg.norm(np.cross(palm_vec_a, palm_vec_b)) < 1.0e-7:
        return False, "degenerate palm frame"
    return True, None


class WujiOfficialManusHandRetargeter:
    """Retarget MANUS/OpenXR-style 21-point skeletons with Wuji's package."""

    def __init__(
        self,
        *,
        config_dir: Path,
        left_config_name: str = "left.yaml",
        right_config_name: str = "right.yaml",
    ) -> None:
        self._config_dir = Path(config_dir).expanduser().resolve()
        self._config_names = {"left": left_config_name, "right": right_config_name}
        self._retargeter_left: Any | None = None
        self._retargeter_right: Any | None = None
        self._left_joint_names: tuple[str, ...] | None = None
        self._right_joint_names: tuple[str, ...] | None = None

    @property
    def left_joint_names(self) -> tuple[str, ...] | None:
        return self._left_joint_names

    @property
    def right_joint_names(self) -> tuple[str, ...] | None:
        return self._right_joint_names

    def _resolve_config_path(self, side: str) -> Path:
        return (self._config_dir / self._config_names[side]).resolve()

    def _ensure_retargeters(self) -> None:
        if self._retargeter_left is not None and self._retargeter_right is not None:
            return

        Retargeter = import_official_wuji_retargeter()
        left_yaml = self._resolve_config_path("left")
        right_yaml = self._resolve_config_path("right")
        for config_path in (left_yaml, right_yaml):
            if not config_path.is_file():
                raise FileNotFoundError(
                    f"Wuji retarget config does not exist: {config_path}"
                )

        self._retargeter_left = Retargeter.from_yaml(str(left_yaml), hand_side="left")
        self._retargeter_right = Retargeter.from_yaml(
            str(right_yaml), hand_side="right"
        )
        self._left_joint_names = tuple(
            self._retargeter_left.optimizer.robot.dof_joint_names
        )
        self._right_joint_names = tuple(
            self._retargeter_right.optimizer.robot.dof_joint_names
        )

    @staticmethod
    def _retarget_hand(side: str, skeleton: np.ndarray, retargeter: Any) -> np.ndarray:
        valid, error = _valid_skeleton21(skeleton)
        if not valid:
            raise ValueError(f"Invalid {side} hand skeleton: {error}")

        qpos = np.asarray(retargeter.retarget(skeleton), dtype=np.float32).reshape(-1)
        if qpos.shape != (int(retargeter.num_joints),):
            raise RuntimeError(
                f"{side} hand retarget returned {qpos.shape}, expected {(int(retargeter.num_joints),)}"
            )
        if not np.all(np.isfinite(qpos)):
            raise RuntimeError(f"{side} hand retarget returned non-finite values")
        return qpos.copy()

    def retarget_manus_skeletons(
        self,
        left_skeleton: Any,
        right_skeleton: Any,
        *,
        frame_index: int,
        device: Any = None,
    ) -> HandRetargetStepResult:
        del device
        self._ensure_retargeters()
        started = time.perf_counter()

        left_qpos = self._retarget_hand(
            "left",
            _as_float32_numpy(left_skeleton, (21, 3)),
            self._retargeter_left,
        )
        right_qpos = self._retarget_hand(
            "right",
            _as_float32_numpy(right_skeleton, (21, 3)),
            self._retargeter_right,
        )

        return HandRetargetStepResult(
            frame_index=int(frame_index),
            left_joint_positions=left_qpos,
            right_joint_positions=right_qpos,
            left_joint_names=self._left_joint_names,
            right_joint_names=self._right_joint_names,
            ok=True,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def retarget_manus_skeleton(
        self,
        side: str,
        skeleton: Any,
        *,
        frame_index: int,
        device: Any = None,
    ) -> tuple[np.ndarray, tuple[str, ...] | None]:
        del frame_index, device
        self._ensure_retargeters()
        if side == "left":
            return (
                self._retarget_hand(
                    "left",
                    _as_float32_numpy(skeleton, (21, 3)),
                    self._retargeter_left,
                ),
                self._left_joint_names,
            )
        if side == "right":
            return (
                self._retarget_hand(
                    "right",
                    _as_float32_numpy(skeleton, (21, 3)),
                    self._retargeter_right,
                ),
                self._right_joint_names,
            )
        raise ValueError(f"Unsupported hand side: {side!r}")

    def shutdown(self) -> None:
        self._retargeter_left = None
        self._retargeter_right = None
