# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which joints a published snapshot names, and where each one lands in the scene."""

from __future__ import annotations

from typing import Sequence

import numpy as np


class JointMap:
    """Motor name -> the address its position occupies in the twin's state vector.

    A twin is posed with a bare array, so the order is the contract and the names pin it.
    The backend builds this from the loaded scene; the caller asserts it with
    :meth:`require`, without which a reordered upstream scene poses the wrong joints and
    still looks like a robot. Empty is legal, and is what a rigid scene has.
    """

    def __init__(
        self, names: Sequence[str], addresses: Sequence[int], *, width: int
    ) -> None:
        """Bind names to addresses and reject a mapping nothing could scatter through.

        Args:
            names: Motor names, in the order a published snapshot carries them.
            addresses: Where each name's position sits, parallel to ``names``.
            width: Total length of the state vector the addresses index into.

        Raises:
            ValueError: If the two sequences disagree in length, either carries a
                duplicate, or an address falls outside ``width``.
        """
        self._names = tuple(names)
        self._addresses = np.asarray(addresses, dtype=np.int32)
        self._width = int(width)

        if len(self._names) != self._addresses.size:
            raise ValueError(
                f"{len(self._names)} joint names against "
                f"{self._addresses.size} addresses"
            )
        if len(set(self._names)) != len(self._names):
            raise ValueError(f"duplicate joint name in {self._names}")
        # Two names on one address means the second silently overwrites the first every
        # time a snapshot is scattered.
        if np.unique(self._addresses).size != self._addresses.size:
            raise ValueError(f"two joints share an address: {self._addresses.tolist()}")
        if self._addresses.size and (
            self._addresses.min() < 0 or self._addresses.max() >= self._width
        ):
            raise ValueError(
                f"addresses {self._addresses.tolist()} do not all fall inside "
                f"a state vector of width {self._width}"
            )

    def __len__(self) -> int:
        return len(self._names)

    @property
    def names(self) -> tuple[str, ...]:
        """The motor names, in the order a published snapshot carries them."""
        return self._names

    def require(self, expected: Sequence[str]) -> None:
        """Fail unless the scene declares exactly ``expected``, in that order.

        Raises:
            RuntimeError: If a name is missing, extra, or in a different position.
        """
        expected = tuple(expected)
        if self._names == expected:
            return
        missing = [name for name in expected if name not in self._names]
        extra = [name for name in self._names if name not in expected]
        detail = (
            f"missing {missing}, unexpected {extra}"
            if missing or extra
            else f"same joints in a different order: {self._names}"
        )
        raise RuntimeError(
            f"the scene's joints are not the {len(expected)} this was authored "
            f"against ({detail}); a snapshot would pose the wrong joints. Expected "
            f"{expected}, got {self._names}."
        )

    def scatter(self, joints: Sequence[float], positions: np.ndarray) -> None:
        """Write a snapshot ordered by :attr:`names` into ``positions``.

        Raises:
            ValueError: If ``joints`` is not one value per name, or ``positions`` is
                not :attr:`width` long.
        """
        joints = np.asarray(joints, dtype=float)
        if joints.shape != (len(self._names),):
            raise ValueError(
                f"expected {len(self._names)} joint values for {self._names}, "
                f"got shape {joints.shape}"
            )
        if positions.shape[0] != self._width:
            raise ValueError(
                f"state vector is {positions.shape[0]} long, this map addresses "
                f"{self._width}"
            )
        positions[self._addresses] = joints
