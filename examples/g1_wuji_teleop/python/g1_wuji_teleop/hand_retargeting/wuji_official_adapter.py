# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thin wrapper around the vendored official ``wuji-retargeting`` package."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..paths import repo_root
from .base import HandRetargetStepResult

_WUJI_CONFIG_FILENAMES = {
    "left": "manus_wuji_left.yaml",
    "right": "manus_wuji_right.yaml",
}


def _official_checkout_root() -> Path:
    return (repo_root() / "third_party" / "wuji-retargeting").resolve()


def _ensure_upstream_checkout() -> Path:
    checkout_root = _official_checkout_root()
    package_entry = checkout_root / "wuji_retargeting" / "retarget.py"
    if not package_entry.is_file():
        raise ModuleNotFoundError(
            "Official wuji-retargeting checkout is missing. Expected "
            f"{package_entry}. Initialize the submodule first."
        )

    checkout_root_str = str(checkout_root)
    if checkout_root_str not in sys.path:
        sys.path.insert(0, checkout_root_str)
    return checkout_root


def _import_upstream_retargeter():
    _ensure_upstream_checkout()
    from wuji_retargeting.retarget import Retargeter

    return Retargeter


def _as_float32_numpy(values: Any, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    return array.reshape(shape)


def _valid_skeleton21(skeleton: np.ndarray) -> tuple[bool, str | None]:
    if skeleton.shape != (21, 3):
        return False, f"unexpected shape {skeleton.shape}"
    if not np.all(np.isfinite(skeleton)):
        return False, "non-finite landmarks"

    centered = skeleton - skeleton[0:1]
    max_radius = float(np.max(np.linalg.norm(centered, axis=1)))
    if max_radius < 1.0e-4:
        return False, "all landmarks collapsed to the wrist"

    palm_vec_a = skeleton[5] - skeleton[0]
    palm_vec_b = skeleton[9] - skeleton[0]
    if np.linalg.norm(palm_vec_a) < 1.0e-5 or np.linalg.norm(palm_vec_b) < 1.0e-5:
        return False, "missing palm anchor landmarks"
    if np.linalg.norm(np.cross(palm_vec_a, palm_vec_b)) < 1.0e-7:
        return False, "degenerate palm frame"
    return True, None


class WujiOfficialManusHandRetargeter:
    """Retarget MANUS/OpenXR-style 21-point skeletons with the official package."""

    def __init__(
        self,
        *,
        config_dir: Path | None = None,
        left_config_name: str = _WUJI_CONFIG_FILENAMES["left"],
        right_config_name: str = _WUJI_CONFIG_FILENAMES["right"],
    ) -> None:
        self._config_dir = (
            Path(config_dir).expanduser() if config_dir is not None else None
        )
        self._config_names = {
            "left": left_config_name,
            "right": right_config_name,
        }
        self._retargeter_left: Any | None = None
        self._retargeter_right: Any | None = None
        self._left_joint_names: tuple[str, ...] | None = None
        self._right_joint_names: tuple[str, ...] | None = None
        self._last_left = np.zeros(20, dtype=np.float32)
        self._last_right = np.zeros(20, dtype=np.float32)

    def _resolve_config_path(self, side: str) -> Path:
        if self._config_dir is not None:
            return (self._config_dir / self._config_names[side]).resolve()

        upstream_root = _ensure_upstream_checkout()
        return (
            upstream_root / "example" / "config" / f"retarget_manus_{side}.yaml"
        ).resolve()

    def _ensure_retargeters(self) -> None:
        if self._retargeter_left is not None and self._retargeter_right is not None:
            return

        Retargeter = _import_upstream_retargeter()
        left_yaml = self._resolve_config_path("left")
        right_yaml = self._resolve_config_path("right")
        for config_path in (left_yaml, right_yaml):
            if not config_path.is_file():
                raise FileNotFoundError(
                    f"Official Wuji retarget config does not exist: {config_path}"
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

    def _safe_qpos(self, retargeter: Any, cached: np.ndarray | None) -> np.ndarray:
        num_joints = int(retargeter.num_joints)
        if cached is not None:
            cached_array = np.asarray(cached, dtype=np.float32).reshape(-1)
            if cached_array.shape == (num_joints,) and np.all(
                np.isfinite(cached_array)
            ):
                return cached_array.copy()

        limits = np.asarray(retargeter.optimizer.robot.joint_limits, dtype=np.float32)
        zeros = np.zeros(num_joints, dtype=np.float32)
        return np.clip(zeros, limits[:, 0], limits[:, 1])

    def _retarget_hand(
        self,
        side: str,
        skeleton: np.ndarray,
        retargeter: Any,
        cached_qpos: np.ndarray,
    ) -> tuple[np.ndarray, bool, str | None]:
        safe_qpos = self._safe_qpos(retargeter, cached_qpos)
        valid, error = _valid_skeleton21(skeleton)
        if not valid:
            return safe_qpos, False, f"invalid {side} hand skeleton: {error}"

        try:
            qpos = np.asarray(retargeter.retarget(skeleton), dtype=np.float32).reshape(
                -1
            )
        except Exception as exc:
            retargeter.reset()
            return safe_qpos, False, f"{side} hand retarget failed ({exc})"

        if qpos.shape != safe_qpos.shape:
            retargeter.reset()
            return (
                safe_qpos,
                False,
                f"{side} hand retarget returned {qpos.shape}, expected {safe_qpos.shape}",
            )
        if not np.all(np.isfinite(qpos)):
            retargeter.reset()
            return safe_qpos, False, f"{side} hand retarget returned non-finite values"
        return qpos.copy(), True, None

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

        left_input = _as_float32_numpy(left_skeleton, (21, 3))
        right_input = _as_float32_numpy(right_skeleton, (21, 3))
        left_qpos, left_ok, left_error = self._retarget_hand(
            "left",
            left_input,
            self._retargeter_left,
            self._last_left,
        )
        right_qpos, right_ok, right_error = self._retarget_hand(
            "right",
            right_input,
            self._retargeter_right,
            self._last_right,
        )

        if left_ok:
            self._last_left = left_qpos.copy()
        if right_ok:
            self._last_right = right_qpos.copy()

        errors = [error for error in (left_error, right_error) if error]
        return HandRetargetStepResult(
            frame_index=int(frame_index),
            left_joint_positions=left_qpos,
            right_joint_positions=right_qpos,
            left_joint_names=self._left_joint_names,
            right_joint_names=self._right_joint_names,
            ok=left_ok and right_ok,
            stale=not (left_ok and right_ok),
            error="; ".join(errors) if errors else None,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            raw={
                "left_ok": left_ok,
                "right_ok": right_ok,
            },
        )

    def shutdown(self) -> None:
        self._retargeter_left = None
        self._retargeter_right = None
