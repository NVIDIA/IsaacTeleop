# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Manus Metagloves Pro Haptic adapter.

Bridges :class:`IHapticDevice` to the Manus plugin singleton via a small
pybind11 module (``_manus_haptic``). The plugin singleton must already be
alive -- the Manus hand-tracking plugin sets it up, and its connection
lifecycle is managed there. This adapter only forwards per-finger powers
to ``CoreSdk_VibrateFingersForGlove`` through the plugin's haptic entry
point.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.tensor_types import (
    FingerPowerVector,
    NUM_HAPTIC_FINGERS,
)

from .interface import IHapticDevice


logger = logging.getLogger(__name__)


class ManusHapticDevice(IHapticDevice):
    """:class:`IHapticDevice` adapter for the Manus Metagloves Pro Haptic glove.

    Consumes :func:`FingerPowerVector(num_fingers=5) <isaacteleop.retargeting_engine.tensor_types.FingerPowerVector>`
    in Manus order ``[Thumb, Index, Middle, Ring, Pinky]`` with values in
    ``[0, 1]`` (the C++ side clamps; values outside the range are silently
    rounded in). ``apply()`` is a thin shim over the pybind module that
    forwards to ``ManusTracker::apply_haptic_command`` -- vendor SDK linkage
    stays inside ``src/plugins/manus/`` per the AGENTS.md boundary.

    The pybind module is imported lazily on the first :meth:`apply` call so
    importing :mod:`isaacteleop.haptic_devices.manus` does not require the
    Manus SDK to be installed; an ``ImportError`` with a clear message is
    raised at use time if the SDK is missing.
    """

    def __init__(self, num_fingers: int = NUM_HAPTIC_FINGERS) -> None:
        """Construct a Manus haptic adapter.

        Args:
            num_fingers: Channel count. Manus hardware fixes this to 5;
                exposed for parity with :func:`FingerPowerVector` and to
                catch mis-wired pipelines at ``connect()`` time.
        """
        self._num_fingers = num_fingers
        # Lazy-imported on first apply(); set once for the lifetime of the process.
        self._pybind = None
        # Log hardware errors at most once per side to keep the pipeline log clean.
        self._error_logged: dict[str, bool] = {"left": False, "right": False}

    def accepted_type(self) -> TensorGroupType:
        return FingerPowerVector(self._num_fingers)

    def apply(self, side: Literal["left", "right"], values: np.ndarray) -> None:
        pybind = self._get_pybind()
        if pybind is None:
            return

        # Force the shape and dtype the C++ side expects. NumPy view; no copy
        # when the upstream retargeter already produced a contiguous float32.
        arr = np.asarray(values, dtype=np.float32).ravel()
        if arr.size != self._num_fingers:
            raise ValueError(
                f"ManusHapticDevice.apply expects a {self._num_fingers}-element "
                "FingerPowerVector "
                f"(order [Thumb, Index, Middle, Ring, Pinky]), got shape {np.asarray(values).shape}"
            )
        powers = arr.reshape(self._num_fingers)
        try:
            pybind.apply_haptic_command(side, powers)
        except Exception as exc:
            if not self._error_logged[side]:
                logger.warning(
                    "ManusHapticDevice.apply(%s) failed (will silence further "
                    "errors for this side): %s",
                    side,
                    exc,
                )
                self._error_logged[side] = True

    def _get_pybind(self):
        """Lazy-import the Manus haptic pybind module.

        Cached after first successful import. When the module is unavailable
        (Manus SDK not installed at build time), logs once and returns ``None``
        so the pipeline keeps running -- haptic feedback is a nice-to-have,
        not a session-fatal dependency.
        """
        if self._pybind is not None:
            return self._pybind
        try:
            from . import _manus_haptic  # type: ignore[import-not-found]
        except ImportError as exc:
            if not self._error_logged["left"]:
                # Reuse one error_logged slot; the message is identical for both sides.
                logger.warning(
                    "ManusHapticDevice unavailable: %s. "
                    "Build the Manus plugin (src/plugins/manus/) with the "
                    "Manus SDK installed to enable haptic output.",
                    exc,
                )
                self._error_logged["left"] = True
                self._error_logged["right"] = True
            return None
        self._pybind = _manus_haptic
        return self._pybind
