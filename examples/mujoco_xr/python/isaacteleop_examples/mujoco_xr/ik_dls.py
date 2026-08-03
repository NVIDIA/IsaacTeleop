# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Damped-least-squares IK for a position-servo arm, plus the ids it needs.

    dq = J' (J J' + lambda^2 I6)^-1 e

6x6 solve via ``mju_cholFactor`` / ``mju_cholSolve``; rotation error from a
local-frame ``mju_subQuat`` rotated into world; nullspace home-posture bias
projected through the same damped pseudoinverse. Ported from
``MuJoCoXR/src/ik_dls.{h,c}``. No scipy, and no allocation on the per-frame
path: every buffer is sized once in ``__init__`` and mutated in place.

It is deliberately NOT only the mathematics. The solver is written against one
arm at a time, and which arm that is comes from ``robot_spec.ROBOTS`` -- so this
module owns the RESOLUTION step as well: ``mj_name2id`` over that robot's table
row, once, into the index arrays below. Everything downstream (``teleop.py``,
``app.py``) reads resolved ids and never a name. The arm is 5 dofs on one shipped
robot and 7 on the other; the task is 6D on both, so J is 6 x narm and may be
rank-deficient in either direction.

WHY THIS IS PYTHON AND NOT C++: ``cpp/scene_renderer.hpp`` already draws the
line -- C++ owns ``mjvScene`` / ``mjvOption`` / ``mjvCamera``, Python owns
``mjModel`` / ``mjData`` / ``mj_step``. Control writes ``d.ctrl``, so it is on
the Python side of that line. It also makes the whole control stack testable
with no GPU, no headset and no runtime, which is what ``tests/test_ik_dls.py``
and ``tests/test_teleop.py`` are.
"""

from __future__ import annotations

import mujoco
import numpy as np

from . import robot_spec


class IkDls:
    """One arm's resolved ids, tuned constants and scratch space.

    Constructed once per loaded model. Raises ``ValueError`` naming the FIRST
    name that failed to resolve INSIDE the matched row -- that is the whole value
    of probing before resolving: without it, a typo in one joint name is
    indistinguishable from "wrong robot", and the caller is left bisecting five
    names by hand.

    The message matters more than it looks. The one caller turns a failure into
    "control is not available", and a scene with no control still RENDERS. The
    symptom is therefore a robot that draws perfectly and never moves, which on a
    headset is indistinguishable from a dead controller. This string is what
    tells the two apart, so callers must log it.
    """

    def __init__(self, model):
        # WHICH robot is a property of the model, never an argument. A caller
        # cannot assert a robot this model is not.
        self.spec: robot_spec.Robot = robot_spec.robot_probe(model)
        spec = self.spec
        self.narm = spec.narm

        self.tcp_body = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, spec.tcp_body
        )
        if self.tcp_body < 0:  # pragma: no cover - robot_probe just found it
            raise ValueError(
                f"body '{spec.tcp_body}' vanished between probe and resolve"
            )

        # Not a table name: every scene wrapper must author this keyframe, and
        # both the A-reset and qhome read it.
        key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
        if key < 0:
            raise ValueError(
                f"robot '{spec.tcp_body}' resolved, but the scene has no keyframe "
                "named 'home'"
            )
        self.home_key = key

        dofadr = np.zeros(self.narm, dtype=np.int32)
        qposadr = np.zeros(self.narm, dtype=np.int32)
        act = np.zeros(self.narm, dtype=np.int32)
        self.qhome = np.zeros(self.narm)
        # ctrlrange INTERSECT jnt_range, once, here.
        #
        # BOTH EXIST AND THEY ARE NOT THE SAME CONSTRAINT. On the SO-101, 2 of
        # the 5 ARM joints have an intersection that differs from ctrlrange:
        # shoulder_lift by 1e-6 rad (immaterial) and wrist_roll by 0.0973 rad,
        # whose ctrlrange is that much WIDER than the joint can travel. So
        # wrist_roll is the whole of this, and it is worth the precompute for
        # what MEASURING the old path showed:
        #
        #   clamp to ctrlrange     qpos 2.745940  |qfrc_constraint| 2.937977 N.m
        #                          qfrc_actuator  2.940000          nlim 1
        #   clamp to intersection  qpos 2.743845  |qfrc_constraint| 0.000000 N.m
        #                          qfrc_actuator  0.002011          nlim 0
        #
        # 2.940000 is EXACTLY actuator_forcerange for every SO-101 joint.
        # Commanding to ctrlrange alone did not merely stall the joint short of
        # its target: it parked wrist_roll at 100 % of rated torque against a
        # live mjCNSTR_LIMIT_JOINT constraint and held it there indefinitely,
        # because nothing in the loop ever backs off. In sim that is a wasted
        # 2.9 N.m; on the real servo it is a stalled motor at rated current until
        # thermal shutdown, and it is the strongest reason this intersection
        # exists.
        #
        # THE PANDA'S TWO RANGES ARE BITWISE EQUAL ON ALL 7 JOINTS, so taking the
        # intersection is a structural identity there rather than a change that
        # happens not to fire -- and therefore a Franka-only test structurally
        # CANNOT detect a bug in this block. The SO-101's can, and
        # tests/test_ik_dls.py runs it there.
        self.ctrl_lo = np.full(self.narm, -mujoco.mjMAXVAL)
        self.ctrl_hi = np.full(self.narm, mujoco.mjMAXVAL)

        for i, joint in enumerate(spec.joints):
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
            if jid < 0:
                raise ValueError(
                    f"robot '{spec.tcp_body}': joint '{joint}' not in this model"
                )
            dofadr[i] = model.jnt_dofadr[jid]
            qposadr[i] = model.jnt_qposadr[jid]
            self.qhome[i] = model.key_qpos[key][qposadr[i]]

            found = -1
            for a in range(model.nu):
                if (
                    model.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT
                    and model.actuator_trnid[a][0] == jid
                ):
                    found = a
                    break
            if found < 0:
                raise ValueError(
                    f"robot '{spec.tcp_body}': joint '{joint}' has no "
                    "position-servo actuator"
                )
            act[i] = found

            # An unlimited side contributes mjMAXVAL, so an unconstrained joint
            # clamps against a bound no reachable pose can hit.
            if model.actuator_ctrllimited[found]:
                self.ctrl_lo[i] = model.actuator_ctrlrange[found][0]
                self.ctrl_hi[i] = model.actuator_ctrlrange[found][1]
            if model.jnt_limited[jid]:
                self.ctrl_lo[i] = max(self.ctrl_lo[i], model.jnt_range[jid][0])
                self.ctrl_hi[i] = min(self.ctrl_hi[i], model.jnt_range[jid][1])

        self.dofadr = dofadr
        self.qposadr = qposadr
        self.act = act

        self.gripper_act = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_ACTUATOR, spec.gripper_act
        )
        if self.gripper_act < 0:
            raise ValueError(
                f"robot '{spec.tcp_body}': gripper actuator '{spec.gripper_act}' "
                "not in this model"
            )

        # Position-servo gain per arm actuator, for the gravity feed-forward.
        # Read once: it is model data, not state.
        self._kp = np.array(
            [model.actuator_gainprm[a][0] for a in act], dtype=np.float64
        )
        # kp <= 0 means "not a position servo with a usable gain"; the
        # feed-forward is then dropped for that joint rather than dividing by it.
        self._kp_safe = np.where(self._kp > 0.0, self._kp, 1.0)
        self._kp_live = self._kp > 0.0

        # ---- scratch, sized once, mutated in place ------------------------
        self._tcp_offset = np.array(spec.tcp_offset, dtype=np.float64)
        self._off = np.zeros(3)
        self._tcp_pos = np.zeros(3)
        self._tcp_quat = np.zeros(4)
        self._jacp = np.zeros((3, model.nv))
        self._jacr = np.zeros((3, model.nv))
        self._J = np.zeros((6, self.narm))
        self._A = np.zeros((6, 6))
        self._e = np.zeros(6)
        self._e_local = np.zeros(3)
        self._y = np.zeros(6)
        self._z = np.zeros(self.narm)
        self._Jz = np.zeros(6)
        self._w = np.zeros(6)
        self._corr = np.zeros(self.narm)
        self._q = np.zeros(self.narm)
        self._sag = np.zeros(self.narm)
        self._c = np.zeros(self.narm)
        # The public output of solve(). Reused every frame: a caller that wants
        # to keep it across frames must copy.
        self.dq = np.zeros(self.narm)

    # -----------------------------------------------------------------------

    def tcp(self, data, pos=None, quat=None):
        """World pose of the TCP from current mjData kinematics.

        ``quat`` is the ``tcp_body`` frame, which is NOT a common convention
        across robots -- see ``robot_spec.Robot.tcp_body`` and the orientation
        block in ``teleop.py``.

        With no arguments this returns the module's own scratch buffers, which
        the next call overwrites. Pass your own arrays to keep the result.
        """
        pos = self._tcp_pos if pos is None else pos
        quat = self._tcp_quat if quat is None else quat
        q = data.xquat[self.tcp_body]
        mujoco.mju_rotVecQuat(self._off, self._tcp_offset, q)
        np.add(data.xpos[self.tcp_body], self._off, out=pos)
        quat[:] = q
        return pos, quat

    def solve(self, model, data, target_pos, target_quat):
        """One DLS step toward the target. Returns ``self.dq`` (narm entries)."""
        narm = self.narm
        w_rot = self.spec.w_rot
        p_tcp, q_tcp = self.tcp(data)

        # mj_jac AT THE OFFSET TCP POINT, never mj_jacBody at the body origin:
        # the body-origin Jacobian silently drops the 103 mm (Franka) / 98 mm
        # (SO-101) tool offset and changes the rotation->translation coupling, so
        # a commanded rotation moves the fingertips somewhere else.
        mujoco.mj_jac(model, data, self._jacp, self._jacr, p_tcp, self.tcp_body)

        # 6D task error: position, then local-frame subQuat rotated into world.
        e = self._e
        mujoco.mju_sub3(e[:3], target_pos, p_tcp)
        mujoco.mju_subQuat(self._e_local, target_quat, q_tcp)  # argument order
        mujoco.mju_rotVecQuat(e[3:], self._e_local, q_tcp)

        # ROTATION WEIGHT. Scaling the bottom three rows of BOTH e and J is what
        # makes the least-squares problem minimise |e_pos|^2 + w^2 |e_rot|^2 --
        # the weight has to appear in the same places a change of task UNITS
        # would, or it is not a metric change but an arbitrary bias. w_rot = 1.0
        # is exactly the identity (x * 1.0 is bitwise x), which is why the
        # Franka's behaviour is unmoved by this block existing.
        e[3:] *= w_rot

        # J: 6 x narm arm columns of [jacp; w_rot * jacr].
        np.take(self._jacp, self.dofadr, axis=1, out=self._J[0:3])
        np.take(self._jacr, self.dofadr, axis=1, out=self._J[3:6])
        self._J[3:6] *= w_rot

        # A = J J' + lambda^2 I6, Cholesky-factored in place.
        lam = self.spec.dls_lambda
        mujoco.mju_mulMatMatT(self._A, self._J, self._J)
        self._A[np.diag_indices(6)] += lam * lam
        mujoco.mju_cholFactor(self._A, 0.0)

        # Task step: dq = J' A^-1 e.
        mujoco.mju_cholSolve(self._y, self._A, e)
        mujoco.mju_mulMatTVec(self.dq, self._J, self._y)

        # Nullspace home bias: dq += (I - J^+ J) z, z = k (qhome - q),
        # J^+ = J' A^-1.
        #
        # ONLY MEANINGFUL WHEN THE ARM HAS A NULLSPACE, i.e. narm > 6 --
        # enforced as a load-time error in robot_spec._validate, so this branch
        # can never run on an arm that has none. What it computes is the DAMPED
        # projector, which is not a projector: it leaks as lambda^2/sigma^2, and
        # on a column-rank-full arm every bit of `z` that survives lands on the
        # task command as uncommanded tool motion.
        ns_gain = self.spec.ns_gain
        if ns_gain != 0.0:
            np.take(data.qpos, self.qposadr, out=self._q)
            np.subtract(self.qhome, self._q, out=self._z)
            self._z *= ns_gain
            mujoco.mju_mulMatVec(self._Jz, self._J, self._z)
            mujoco.mju_cholSolve(self._w, self._A, self._Jz)
            mujoco.mju_mulMatTVec(self._corr, self._J, self._w)
            self.dq += self._z
            self.dq -= self._corr
        assert narm == self.dq.shape[0]
        return self.dq

    def write_ctrl(self, model, data, dq=None):
        """``ctrl[arm] = clamp(qpos + dq + sag, ctrl_lo, ctrl_hi)``. Jaw untouched.

        THE JAW IS DELIBERATELY NOT CLAMPED HERE: it is not an arm joint, it is
        written every frame by ``teleop.Teleop.update`` from the tabulated
        endpoints, and clamping it to a joint range would silently re-scale a
        polarity this app tabulates on purpose.
        """
        dq = self.dq if dq is None else dq
        np.take(data.qpos, self.qposadr, out=self._q)
        # GRAVITY FEED-FORWARD. A position servo settles at ctrl - qfrc_bias/kp,
        # so the sag is added back to make the HELD pose track the IK solution.
        # Without it the arm droops below the solution permanently and reads as
        # an IK bias -- a constant offset that no amount of gain tuning removes,
        # because it is not an IK error at all.
        np.take(data.qfrc_bias, self.dofadr, out=self._sag)
        self._sag /= self._kp_safe
        self._sag *= self._kp_live
        np.add(self._q, dq, out=self._c)
        self._c += self._sag
        np.clip(self._c, self.ctrl_lo, self.ctrl_hi, out=self._c)
        data.ctrl[self.act] = self._c
        return self._c
