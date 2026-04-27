# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Sharpa Hand Retargeter Module.

Retargeter for the Sharpa dexterous hand using Pinocchio + Pink IK.
Converts OpenXR hand tracking data (26 joints) into Sharpa robot joint angles
via frame-task-based inverse kinematics.

Ported from robotic_grounding SharpaHandKinematics, adapted for Isaac Teleop's
retargeting framework.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pinocchio as pin
import pink
from loop_rate_limiters import RateLimiter
from pink import solve_ik
from pink.limits import ConfigurationLimit, VelocityLimit
from pink.tasks import FrameTask
from scipy.spatial.transform import Rotation as R

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    TensorGroupType,
    OptionalType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    HandInput,
    FloatType,
    HandInputIndex,
    HandJointIndex,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MANO joint order (21 joints) — matches the source hand_kinematics ordering
# ---------------------------------------------------------------------------

MANO_JOINTS_ORDER: list[str] = [
    "wrist",
    "thumb1",
    "thumb2",
    "thumb3",
    "thumb4",
    "index1",
    "index2",
    "index3",
    "index4",
    "middle1",
    "middle2",
    "middle3",
    "middle4",
    "ring1",
    "ring2",
    "ring3",
    "ring4",
    "pinky1",
    "pinky2",
    "pinky3",
    "pinky4",
]

# ---------------------------------------------------------------------------
# OpenXR (26 joints) → MANO (21 joints) index mapping
# Skips OpenXR palm(0) and metacarpal joints for non-thumb fingers.
# ---------------------------------------------------------------------------

_OPENXR_TO_MANO_INDICES: list[int] = [
    HandJointIndex.WRIST,  # wrist
    HandJointIndex.THUMB_METACARPAL,  # thumb1
    HandJointIndex.THUMB_PROXIMAL,  # thumb2
    HandJointIndex.THUMB_DISTAL,  # thumb3
    HandJointIndex.THUMB_TIP,  # thumb4
    HandJointIndex.INDEX_PROXIMAL,  # index1
    HandJointIndex.INDEX_INTERMEDIATE,  # index2
    HandJointIndex.INDEX_DISTAL,  # index3
    HandJointIndex.INDEX_TIP,  # index4
    HandJointIndex.MIDDLE_PROXIMAL,  # middle1
    HandJointIndex.MIDDLE_INTERMEDIATE,  # middle2
    HandJointIndex.MIDDLE_DISTAL,  # middle3
    HandJointIndex.MIDDLE_TIP,  # middle4
    HandJointIndex.RING_PROXIMAL,  # ring1
    HandJointIndex.RING_INTERMEDIATE,  # ring2
    HandJointIndex.RING_DISTAL,  # ring3
    HandJointIndex.RING_TIP,  # ring4
    HandJointIndex.LITTLE_PROXIMAL,  # pinky1
    HandJointIndex.LITTLE_INTERMEDIATE,  # pinky2
    HandJointIndex.LITTLE_DISTAL,  # pinky3
    HandJointIndex.LITTLE_TIP,  # pinky4
]

# ---------------------------------------------------------------------------
# Sharpa-specific IK parameters (from robotic_grounding params.py)
# ---------------------------------------------------------------------------

# Rotation offset applied to the wrist frame to align Sharpa with MANO.
# Key uses ".*" as a side placeholder; value is wxyz quaternion.
_SHARPA_TO_MANO_ROTATION_OFFSET: dict[str, tuple[float, float, float, float]] = {
    ".*_hand_C_MC": (0.5, -0.5, 0.5, 0.5),
}

# Mapping from Sharpa robot frame sites to MANO joint names with IK costs.
# {robot_site_pattern: (mano_joint, position_cost, orientation_cost)}
_SHARPA_TO_MANO_MAPPING: dict[str, tuple[str, float, float]] = {
    ".*_hand_C_MC": ("wrist", 0.2, 0.2),
    ".*_thumb_MCP_VL_site": ("thumb2", 0.1, 0.0),
    ".*_thumb_tip_site": ("thumb4", 1.0, 0.05),
    ".*_index_MP_site": ("index1", 0.1, 0.0),
    ".*_index_tip_site": ("index4", 1.0, 0.1),
    ".*_middle_MP_site": ("middle1", 0.1, 0.0),
    ".*_middle_tip_site": ("middle4", 1.0, 0.1),
    ".*_ring_MP_site": ("ring1", 0.1, 0.0),
    ".*_ring_tip_site": ("ring4", 1.0, 0.1),
    ".*_pinky_MP_site": ("pinky1", 0.1, 0.0),
    ".*_pinky_tip_site": ("pinky4", 0.5, 0.1),
}


@dataclass
class SharpaHandRetargeterConfig:
    """Configuration for the Sharpa hand retargeter.

    Attributes:
        robot_asset_path: Path to the Sharpa MJCF file (e.g. right_sharpawave.xml).
        hand_side: Which hand to retarget ("left" or "right").
        hand_joint_names: Output joint ordering override. If None, uses
            the finger joint names discovered from the MJCF model.
        source_to_robot_scale: Scale factor from MANO to robot coordinates.
        solver: QP solver backend for Pink IK (e.g. "daqp").
        max_iter: Maximum IK iterations per frame.
        frequency: IK rate-limiter frequency [Hz], used to compute dt.
        frame_tasks_converged_threshold: Per-task position-error convergence
            threshold [m] for early termination.
        parameter_config_path: Optional path to a JSON file for saving/loading
            tunable parameters.
    """

    robot_asset_path: str
    hand_side: str = "right"
    hand_joint_names: list[str] | None = None
    source_to_robot_scale: float = 1.0
    solver: str = "daqp"
    max_iter: int = 200
    frequency: float = 200.0
    frame_tasks_converged_threshold: float = 1e-6
    parameter_config_path: str | None = None


class SharpaHandRetargeter(BaseRetargeter):
    """Retargets OpenXR hand tracking to Sharpa hand joint angles via Pink IK.

    Uses Pinocchio to load the Sharpa MJCF model (with a FreeFlyer root joint)
    and Pink to solve frame-task-based IK that maps MANO joint positions /
    orientations extracted from OpenXR hand tracking onto Sharpa robot frame
    sites.

    Inputs:
        - "hand_{side}": OpenXR hand tracking data (26 joints)

    Outputs:
        - "hand_joints": Sharpa finger joint angles (22 DOFs)
    """

    # Number of FreeFlyer DOFs prepended to qpos by Pinocchio
    _FREEFLYER_NQ = 7

    def __init__(self, config: SharpaHandRetargeterConfig, name: str) -> None:
        self._config = config
        self._hand_side = config.hand_side.lower()
        if self._hand_side not in ("left", "right"):
            raise ValueError(
                f"hand_side must be 'left' or 'right', got: {self._hand_side}"
            )

        # Load the MJCF via Pinocchio with a free-floating root
        self._robot = pin.RobotWrapper.BuildFromMJCF(
            filename=config.robot_asset_path,
            root_joint=pin.JointModelFreeFlyer(),
        )

        # Extract finger joint names (everything after the FreeFlyer joints).
        # Pinocchio model.names[0] = "universe", [1] = "root_joint",
        # then [2..] are the actual finger joints.
        self._finger_joint_names: list[str] = []
        for i in range(2, self._robot.model.njoints):
            self._finger_joint_names.append(self._robot.model.names[i])

        if config.hand_joint_names is None:
            self._hand_joint_names = list(self._finger_joint_names)
        else:
            override = list(config.hand_joint_names)
            if len(override) != len(set(override)):
                seen: set[str] = set()
                dupes = [n for n in override if n in seen or seen.add(n)]  # type: ignore[func-returns-value]
                raise ValueError(f"hand_joint_names contains duplicates: {dupes}")
            finger_set = set(self._finger_joint_names)
            unknown = [n for n in override if n not in finger_set]
            if unknown:
                raise ValueError(
                    f"hand_joint_names contains names not found in the MJCF "
                    f"model's finger joints: {unknown}. "
                    f"Valid names: {self._finger_joint_names}"
                )
            self._hand_joint_names = override

        # Build side-resolved Sharpa→MANO mapping
        self._target_to_source: dict[str, tuple[str, float, float]] = {
            k.replace(".*", self._hand_side): v
            for k, v in _SHARPA_TO_MANO_MAPPING.items()
        }

        # Precompute per-frame rotation corrections
        self._rotation_corrections: dict[str, np.ndarray] = {}
        for pattern, offset_wxyz in _SHARPA_TO_MANO_ROTATION_OFFSET.items():
            frame_name = pattern.replace(".*", self._hand_side)
            self._rotation_corrections[frame_name] = (
                R.from_quat(offset_wxyz, scalar_first=True).inv().as_matrix()
            )

        # Setup Pink solver components
        self._configuration_limits = [
            ConfigurationLimit(self._robot.model),
            VelocityLimit(self._robot.model),
        ]
        self._configuration = pink.Configuration(
            self._robot.model,
            self._robot.data,
            self._robot.q0,
        )

        rate = RateLimiter(frequency=config.frequency, warn=False)
        self._dt = rate.period
        self._solver = config.solver
        self._max_iter = config.max_iter
        self._convergence_threshold = config.frame_tasks_converged_threshold
        self._source_to_robot_scale = config.source_to_robot_scale

        # Build IK frame tasks from the mapping
        self._frame_tasks: dict[str, FrameTask] = {}
        for robot_site, (_, pos_cost, ori_cost) in self._target_to_source.items():
            task = FrameTask(
                robot_site,
                position_cost=pos_cost,
                orientation_cost=ori_cost,
                lm_damping=1.0,
            )
            task.set_target_from_configuration(self._configuration)
            self._frame_tasks[robot_site] = task

        # Warm-start state: persists across frames
        self._qpos_prev: np.ndarray | None = None

        # Index mapping from full qpos to finger-only output
        self._finger_qpos_start = self._FREEFLYER_NQ
        self._finger_qpos_end = self._robot.model.nq

        # Precomputed lookup: finger joint name -> output index
        self._hand_joint_name_to_idx = {
            name: idx for idx, name in enumerate(self._hand_joint_names)
        }

        super().__init__(name=name)

    # ------------------------------------------------------------------
    # BaseRetargeter contract
    # ------------------------------------------------------------------

    def input_spec(self) -> RetargeterIOType:
        """Define input: optional hand tracking for the configured side."""
        key = f"hand_{self._hand_side}"
        return {key: OptionalType(HandInput())}

    def output_spec(self) -> RetargeterIOType:
        """Define output: Sharpa finger joint angles."""
        return {
            "hand_joints": TensorGroupType(
                f"hand_joints_{self._hand_side}",
                [FloatType(name) for name in self._hand_joint_names],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        output_group = outputs["hand_joints"]
        hand_group = inputs[f"hand_{self._hand_side}"]

        if hand_group.is_none:
            for i in range(len(self._hand_joint_names)):
                output_group[i] = 0.0
            self._qpos_prev = None
            return

        joint_positions = np.from_dlpack(
            hand_group[HandInputIndex.JOINT_POSITIONS]
        )  # (26, 3)
        joint_orientations = np.from_dlpack(
            hand_group[HandInputIndex.JOINT_ORIENTATIONS]
        )  # (26, 4) xyzw
        joint_valid = np.from_dlpack(hand_group[HandInputIndex.JOINT_VALID])  # (26,)

        wrist_idx = HandJointIndex.WRIST
        if not joint_valid[wrist_idx]:
            for i in range(len(self._hand_joint_names)):
                output_group[i] = 0.0
            self._qpos_prev = None
            return

        # Extract MANO-ordered positions and orientations from OpenXR
        mano_positions = np.zeros((21, 3), dtype=np.float64)
        mano_quats_wxyz = np.zeros((21, 4), dtype=np.float64)
        mano_quats_wxyz[:, 0] = 1.0
        mano_valid = np.zeros(21, dtype=bool)

        for mano_idx, xr_idx in enumerate(_OPENXR_TO_MANO_INDICES):
            if joint_valid[xr_idx]:
                mano_positions[mano_idx] = joint_positions[xr_idx]
                xyzw = joint_orientations[xr_idx]
                mano_quats_wxyz[mano_idx] = [xyzw[3], xyzw[0], xyzw[1], xyzw[2]]
                mano_valid[mano_idx] = True

        # Build initial qpos with wrist pose
        wrist_pos = mano_positions[0]
        wrist_wxyz = mano_quats_wxyz[0]
        # Pinocchio FreeFlyer quat order is xyzw
        wrist_xyzw = np.array(
            [wrist_wxyz[1], wrist_wxyz[2], wrist_wxyz[3], wrist_wxyz[0]]
        )

        if self._qpos_prev is None:
            qpos = self._robot.q0.copy()
            qpos[:3] = wrist_pos
            qpos[3:7] = wrist_xyzw
        else:
            qpos = self._qpos_prev.copy()
            qpos[:3] = wrist_pos
            qpos[3:7] = wrist_xyzw

        # Set frame task targets from valid MANO joints only
        active_tasks = self._set_frame_tasks_target(
            mano_positions, mano_quats_wxyz, mano_valid
        )

        if not active_tasks:
            for i in range(len(self._hand_joint_names)):
                output_group[i] = 0.0
            self._qpos_prev = None
            return

        # Solve IK
        qpos = self._solve_ik(qpos, active_tasks)
        self._qpos_prev = qpos.copy()

        # Extract finger joint angles and write to output
        finger_angles = qpos[self._finger_qpos_start : self._finger_qpos_end]
        for i, jname in enumerate(self._finger_joint_names):
            out_idx = self._hand_joint_name_to_idx.get(jname)
            if out_idx is not None:
                output_group[out_idx] = float(finger_angles[i])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_frame_tasks_target(
        self,
        mano_positions: np.ndarray,
        mano_quats_wxyz: np.ndarray,
        mano_valid: np.ndarray,
    ) -> dict[str, FrameTask]:
        """Set IK frame task targets from MANO joint data.

        Only tasks whose corresponding MANO source joint is valid are
        updated and returned. Invalid joints are skipped so they don't
        pull the IK solution toward bogus default positions.

        Returns:
            Dict of robot-frame-name to :class:`FrameTask` for the valid
            subset that should be passed to the solver.
        """
        base_idx = MANO_JOINTS_ORDER.index("wrist")
        base_pos = mano_positions[base_idx].copy()

        active_tasks: dict[str, FrameTask] = {}

        for robot_frame, (mano_joint, _, _) in self._target_to_source.items():
            src_idx = MANO_JOINTS_ORDER.index(mano_joint)

            if not mano_valid[src_idx]:
                continue

            # Position: scaled relative to wrist
            target_pos = (
                base_pos
                + (mano_positions[src_idx] - base_pos) * self._source_to_robot_scale
            )

            # Orientation: convert wxyz quat to rotation matrix
            target_rot = R.from_quat(
                mano_quats_wxyz[src_idx], scalar_first=True
            ).as_matrix()

            # Apply per-frame rotation correction (e.g. wrist alignment)
            if robot_frame in self._rotation_corrections:
                target_rot = target_rot @ self._rotation_corrections[robot_frame]

            task = self._frame_tasks[robot_frame]
            task.transform_target_to_world.translation = target_pos.copy()
            task.transform_target_to_world.rotation = target_rot.copy()
            active_tasks[robot_frame] = task

        return active_tasks

    def _solve_ik(
        self, qpos: np.ndarray, active_tasks: dict[str, FrameTask]
    ) -> np.ndarray:
        """Run iterative Pink IK solver with convergence checking.

        Args:
            qpos: Initial joint configuration (FreeFlyer + finger DOFs).
            active_tasks: Only the frame tasks with valid tracking targets.
        """
        self._configuration.q = qpos.copy()
        tasks = list(active_tasks.values())

        prev_errors: dict[str, float] = {name: float(np.inf) for name in active_tasks}
        converged: dict[str, bool] = {name: False for name in active_tasks}

        for _ in range(self._max_iter):
            vel = solve_ik(
                configuration=self._configuration,
                tasks=tasks,
                dt=self._dt,
                solver=self._solver,
                safety_break=False,
                limits=self._configuration_limits,
            )
            self._configuration.integrate_inplace(vel, self._dt)

            for name, task in active_tasks.items():
                err = float(np.linalg.norm(task.compute_error(self._configuration)[:3]))
                if abs(err - prev_errors[name]) < self._convergence_threshold:
                    converged[name] = True
                prev_errors[name] = err

            if all(converged.values()):
                break

        return self._configuration.q.copy()


class SharpaBiManualRetargeter(BaseRetargeter):
    """Combines left and right Sharpa hand joint angles into a single vector.

    Inputs:
        - "left_hand_joints": Joint angles from a left SharpaHandRetargeter
        - "right_hand_joints": Joint angles from a right SharpaHandRetargeter

    Outputs:
        - "hand_joints": Combined joint angles ordered by target_joint_names
    """

    def __init__(
        self,
        left_joint_names: list[str],
        right_joint_names: list[str],
        target_joint_names: list[str],
        name: str,
    ) -> None:
        self._target_joint_names = target_joint_names
        self._left_joint_names = left_joint_names
        self._right_joint_names = right_joint_names

        super().__init__(name=name)

        self._left_indices: list[int] = []
        self._right_indices: list[int] = []
        self._output_indices_left: list[int] = []
        self._output_indices_right: list[int] = []

        for i, jname in enumerate(target_joint_names):
            if jname in left_joint_names:
                self._output_indices_left.append(i)
                self._left_indices.append(left_joint_names.index(jname))
            elif jname in right_joint_names:
                self._output_indices_right.append(i)
                self._right_indices.append(right_joint_names.index(jname))

        mapped = len(self._output_indices_left) + len(self._output_indices_right)
        if mapped != len(target_joint_names):
            known = set(left_joint_names) | set(right_joint_names)
            missing = [n for n in target_joint_names if n not in known]
            raise ValueError(
                f"target_joint_names contains {len(missing)} name(s) not found "
                f"in left or right joint lists: {missing}"
            )

    def input_spec(self) -> RetargeterIOType:
        """Define input collections for both hands."""
        return {
            "left_hand_joints": TensorGroupType(
                "left_hand_joints",
                [FloatType(name) for name in self._left_joint_names],
            ),
            "right_hand_joints": TensorGroupType(
                "right_hand_joints",
                [FloatType(name) for name in self._right_joint_names],
            ),
        }

    def output_spec(self) -> RetargeterIOType:
        """Define output collections for combined hand joints."""
        return {
            "hand_joints": TensorGroupType(
                "hand_joints_bimanual",
                [FloatType(name) for name in self._target_joint_names],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        left_input = inputs["left_hand_joints"]
        right_input = inputs["right_hand_joints"]
        combined = outputs["hand_joints"]

        for src, dst in zip(self._left_indices, self._output_indices_left):
            combined[dst] = float(left_input[src])

        for src, dst in zip(self._right_indices, self._output_indices_right):
            combined[dst] = float(right_input[src])
