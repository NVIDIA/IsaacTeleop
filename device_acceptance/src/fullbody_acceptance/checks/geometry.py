# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Checks that need a skeleton profile.

Bone lengths carry most of the weight here because they do not depend on posture, so a
size or topology judgement made from them cannot be confounded by what the operator was
doing at the time.
"""

from __future__ import annotations

import math

from ..frames import Frame
from ..profile import FULL_BODY, SkeletonProfile
from .base import Check, Outcome, Severity, Status


class _Welford:
    __slots__ = ("count", "mean", "m2", "minimum", "maximum")

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.minimum = math.inf
        self.maximum = -math.inf

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    @property
    def stdev(self) -> float:
        return math.sqrt(self.m2 / (self.count - 1)) if self.count > 1 else 0.0

    @property
    def cv(self) -> float:
        return self.stdev / self.mean if self.mean > 0 else 0.0


class _ProfileCheck(Check):
    def __init__(self, profile: SkeletonProfile = FULL_BODY) -> None:
        super().__init__()
        self.profile = profile


class _BoneLengthCheck(_ProfileCheck):
    """Accumulates one length distribution per bone, valid endpoints only."""

    min_frames = 30

    def __init__(self, profile: SkeletonProfile = FULL_BODY) -> None:
        super().__init__(profile)
        self.bones: dict[tuple[int, int], _Welford] = {
            bone: _Welford() for bone in profile.bones()
        }

    def _update(self, frame: Frame) -> None:
        joints = frame.joints
        if joints is None:
            return
        for bone, stats in self.bones.items():
            parent, child = bone
            if not (joints[parent].is_valid and joints[child].is_valid):
                continue
            length = math.dist(joints[parent].position, joints[child].position)
            if math.isfinite(length):
                stats.add(length)

    def measured(self) -> dict[tuple[int, int], _Welford]:
        return {bone: s for bone, s in self.bones.items() if s.count > 0}

    def derived_bones(self) -> list[str]:
        """Constantly-zero bones are back-filled endpoints, not broken ones.

        Noitom derives hands from wrists and feet from ankles and marks them valid, so
        those four bones have zero length for the whole session. Reportable as derived
        rather than measured; never a fault.
        """
        return [
            self.profile.bone_name(*bone)
            for bone, stats in self.bones.items()
            if stats.count > 0 and stats.maximum == 0.0
        ]

    def substantive(self) -> dict[tuple[int, int], _Welford]:
        return {
            bone: stats
            for bone, stats in self.measured().items()
            if stats.maximum > 0.0
        }


class BoneLengthConstancy(_BoneLengthCheck):
    name = "skeleton.bone_length_constancy"
    gate = "G2"
    severity = Severity.SOFT
    summary = "Bone lengths are invariant over the session"

    def _result(self) -> Outcome:
        bones = self.substantive()
        if not bones:
            return Outcome(Status.INSUFFICIENT_DATA, "no bone had two valid endpoints")

        worst_bone, worst = max(bones.items(), key=lambda item: item[1].cv)
        measurements = {
            "bones_measured": len(bones),
            "worst_bone": self.profile.bone_name(*worst_bone),
            "worst_cv": worst.cv,
            "worst_range_cm": [
                round(worst.minimum * 100, 2),
                round(worst.maximum * 100, 2),
            ],
            "derived_bones": self.derived_bones(),
        }
        if worst.cv <= self.profile.max_bone_length_cv:
            return Outcome(
                Status.PASS,
                f"worst bone varies {worst.cv:.2%} of its length",
                measurements,
            )
        return Outcome(
            Status.FAIL,
            f"{self.profile.bone_name(*worst_bone)} varies {worst.cv:.1%} of its "
            f"length ({worst.minimum * 100:.1f} to {worst.maximum * 100:.1f} cm), so "
            f"segment lengths are not invariant",
            measurements,
        )


class _StatureCheck(_BoneLengthCheck):
    def chain_length(self) -> float | None:
        """Summed bone lengths from ankle to head; independent of posture."""
        total = 0.0
        chain = self.profile.stature_chain
        for lower, upper in zip(chain, chain[1:]):
            a, b = self.profile.index(lower), self.profile.index(upper)
            stats = self.bones.get((a, b)) or self.bones.get((b, a))
            if stats is None or stats.count == 0:
                return None
            total += stats.mean
        return total


class PositionScaleMetres(_StatureCheck):
    name = "units.position_scale_metres"
    gate = "G2"
    severity = Severity.HARD
    summary = "Positions are in metres"

    def _result(self) -> Outcome:
        stature = self.chain_length()
        if stature is None:
            return Outcome(Status.INSUFFICIENT_DATA, "stature chain incomplete")
        low, high = self.profile.plausible_scale_m
        measurements = {
            "skeletal_height": stature,
            "plausible_range": [low, high],
        }
        if low <= stature <= high:
            return Outcome(Status.PASS, f"skeleton spans {stature:.2f} m", measurements)
        factor = stature / 1.7
        return Outcome(
            Status.FAIL,
            f"the skeleton measures {stature:.1f} units ankle to head, about "
            f"{factor:.0f}x a human in metres, so the positions are not in metres",
            measurements,
        )


class AnthropometricPlausibility(_StatureCheck):
    name = "skeleton.anthropometric_plausibility"
    gate = "G2"
    severity = Severity.SOFT
    summary = "Segment lengths and their ratios are human"

    def _result(self) -> Outcome:
        stature = self.chain_length()
        if stature is None:
            return Outcome(Status.INSUFFICIENT_DATA, "stature chain incomplete")

        ratios = []
        for side in ("LEFT", "RIGHT"):
            upper = self.bones.get(
                (
                    self.profile.index(f"{side}_SHOULDER"),
                    self.profile.index(f"{side}_ELBOW"),
                )
            )
            fore = self.bones.get(
                (
                    self.profile.index(f"{side}_ELBOW"),
                    self.profile.index(f"{side}_WRIST"),
                )
            )
            if upper and fore and upper.count and fore.count and upper.mean > 0:
                ratios.append(fore.mean / upper.mean)

        low, high = self.profile.stature_range_m
        ratio_low, ratio_high = self.profile.forearm_over_upper_arm
        measurements = {
            "skeletal_height": stature,
            "stature_range": [low, high],
            "forearm_over_upper_arm": ratios,
            "ratio_range": [ratio_low, ratio_high],
        }

        problems = []
        if not low <= stature <= high:
            problems.append(
                f"summed ankle-to-head length {stature:.2f} m is outside "
                f"{low:.2f}-{high:.2f} m"
            )
        for ratio in ratios:
            if not ratio_low <= ratio <= ratio_high:
                problems.append(
                    f"forearm is {ratio:.2f} of the upper arm, outside "
                    f"{ratio_low:.2f}-{ratio_high:.2f}"
                )

        if not problems:
            return Outcome(
                Status.PASS,
                f"{stature:.2f} m, forearm/upper-arm "
                f"{'/'.join(f'{r:.2f}' for r in ratios)}",
                measurements,
            )
        return Outcome(Status.FAIL, "; ".join(problems), measurements)


class UpAxis(_ProfileCheck):
    name = "coordinate_frame.up_axis"
    gate = "G2"
    severity = Severity.HARD
    summary = "The up axis is +Y"
    min_frames = 30

    # Measured from head to pelvis rather than from a bounding box, so a T-pose arm span
    # cannot outvote the torso.
    AXIS_NAMES = ("X", "Y", "Z")
    EXPECTED_AXIS = 1
    EXPECTED_SIGN = 1.0
    DOMINANCE = 2.0

    # Below this the torso vector carries no direction at all, which happens when the
    # subject is lying down or the feed is degenerate. Neither is evidence about the up
    # axis, so the check declines rather than reporting the wrong axis.
    MIN_TORSO_M = 0.10

    def __init__(self, profile: SkeletonProfile = FULL_BODY) -> None:
        super().__init__(profile)
        self.total = [0.0, 0.0, 0.0]
        self.samples = 0
        self._head = profile.index("HEAD")
        self._pelvis = profile.index("PELVIS")

    def _update(self, frame: Frame) -> None:
        joints = frame.joints
        if joints is None:
            return
        head, pelvis = joints[self._head], joints[self._pelvis]
        if not (head.is_valid and pelvis.is_valid):
            return
        delta = [h - p for h, p in zip(head.position, pelvis.position)]
        if not all(math.isfinite(component) for component in delta):
            return
        self.samples += 1
        for axis in range(3):
            self.total[axis] += delta[axis]

    def _result(self) -> Outcome:
        if self.samples == 0:
            return Outcome(Status.INSUFFICIENT_DATA, "head or pelvis never valid")
        mean = [component / self.samples for component in self.total]
        magnitudes = [abs(component) for component in mean]
        dominant = max(range(3), key=lambda axis: magnitudes[axis])
        others = max(magnitudes[axis] for axis in range(3) if axis != dominant)
        length = math.sqrt(sum(component * component for component in mean))
        measurements = {
            "mean_pelvis_to_head": mean,
            "torso_length_m": length,
            "dominant_axis": self.AXIS_NAMES[dominant],
            "dominance": magnitudes[dominant] / others if others > 0 else math.inf,
        }

        if length < self.MIN_TORSO_M:
            return Outcome(
                Status.INSUFFICIENT_DATA,
                f"pelvis to head spans only {length:.3f} m, which says nothing about "
                f"the up axis",
                measurements,
            )
        if others > 0 and magnitudes[dominant] / others < self.DOMINANCE:
            return Outcome(
                Status.INSUFFICIENT_DATA,
                f"no axis dominates pelvis-to-head ({mean[0]:.2f}, {mean[1]:.2f}, "
                f"{mean[2]:.2f}); the subject may not be upright",
                measurements,
            )
        if dominant == self.EXPECTED_AXIS and (mean[dominant] * self.EXPECTED_SIGN > 0):
            return Outcome(
                Status.PASS,
                f"+{self.AXIS_NAMES[dominant]} up",
                measurements,
            )
        sign = "+" if mean[dominant] > 0 else "-"
        return Outcome(
            Status.FAIL,
            f"pelvis to head points along {sign}{self.AXIS_NAMES[dominant]}, not "
            f"+Y, so the recording is not Y-up",
            measurements,
        )
