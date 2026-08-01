// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Everything expressed in an XR reference space is declared here and converted
// here, exactly once -- including for the Python side, which reaches these
// functions through the pybind module rather than re-deriving them. Rules:
//
//   - Quaternions cross as xyzw (OpenXR, and therefore Teleop's
//     GRIP_ORIENTATION); MuJoCo is [w, x, y, z]. Reorder on EVERY crossing.
//     viz::Pose3D is wxyz, a third spelling; name every variable q_xyzw or
//     q_wxyz and fill boundary structs field by field.
//   - R_mj_from_xr = Rz(-90deg) * Rx(+90deg). Axis map: XR -Z -> MJ +x,
//     XR +Y -> MJ +z, XR +X -> MJ -y. Testable definition: a point 1 m in
//     front of the operator at eye height h lands at MuJoCo (+1, 0, h)
//     before the workspace translation is applied. tests/test_frames.py
//     checks exactly that.
//   - Crossing rules: p_mj = R * p_xr + t;  q_mj = q_mj_from_xr (x) q_xr.
//
// Identifier direction reads by adjacency: p_mj = mj_from_xr_pos(p_xr).
// Comments use that same `_from_` form and never the A_T_B robotics form, so
// the tree carries one direction vocabulary rather than two.

#include <mujoco/mujoco.h>

#include <array>

namespace mujoco_xr
{

// A handedness CONVENTION. It cannot be wrong at runtime: it is fixed by the
// two specs (OpenXR is y-up / -z-forward, MuJoCo is REP-103 z-up) and by the
// table in every scene XML. If the scene appears rotated 90 degrees, or a
// controller marker moves along the wrong world axis, this is the bug.
//
// NOTE the deliberate divergence from
// examples/retargeting/python/visualize_poses_mujoco_example.py, which applies
// Rx(+90) ONLY. That maps XR-forward to MuJoCo +y, which is not REP-103. Do
// not "fix" this constant back to match it.
inline constexpr std::array<double, 4> kQuatMjFromXr = { 0.5, 0.5, -0.5, -0.5 }; // wxyz

// A WORKSPACE CALIBRATION, and routinely wrong. TWO independent terms, and
// zeroing either one is a bug:
//   x = -1.0  operator standoff: the robot base sits ~1 m in front of the
//             operator. The reference space does not affect this term.
//   z = -0.73 floor datum: MuJoCo z=0 is the table TOP, which stands 0.73 m
//             above the physical floor. This term is only correct when the XR
//             reference space has its origin at the floor. VizSession is
//             hard-wired to LOCAL today (viz_session.cpp make_backend never
//             sets a reference space), whose origin is at the headset's
//             start-of-session position -- so this value is an assumption
//             about where the operator was standing, not a measurement.
// A scene XML that floats its robot above the table, or thickens the table
// downward from z=0, silently invalidates the 0.73 for that scene only.
inline constexpr std::array<double, 3> kTransMjFromXr = { -1.0, 0.0, -0.73 };

// XR quaternion (xyzw) -> MuJoCo world quaternion (wxyz). The ONLY quaternion
// crossing in the app; everything else calls this.
inline std::array<double, 4> mj_from_xr_quat(const std::array<double, 4>& q_xyzw)
{
    const mjtNum q_wxyz[4] = { q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2] }; // reorder
    std::array<double, 4> out{};
    mju_mulQuat(out.data(), kQuatMjFromXr.data(), q_wxyz);
    return out;
}

// XR reference-space point -> MuJoCo world point: R * p + t.
inline std::array<double, 3> mj_from_xr_pos(const std::array<double, 3>& p_xr)
{
    std::array<double, 3> out{};
    mju_rotVecQuat(out.data(), p_xr.data(), kQuatMjFromXr.data());
    for (int i = 0; i < 3; ++i)
    {
        out[i] += kTransMjFromXr[i];
    }
    return out;
}

// Column-major float mat4 of xr_from_mj (the inverse of the above), for
// folding MuJoCo-world geometry into the XR reference space in the renderer:
// p_xr = R^T * (p_mj - t).
inline void xr_from_mj_mat4(float out[16])
{
    mjtNum r[9];
    mju_quat2Mat(r, kQuatMjFromXr.data()); // row-major R
    // Rotation part: R^T, column-major out[c*4 + row] = R^T[row][c] = R[c][row].
    for (int row = 0; row < 3; ++row)
    {
        for (int c = 0; c < 3; ++c)
        {
            out[c * 4 + row] = static_cast<float>(r[c * 3 + row]);
        }
        out[row * 4 + 3] = 0.0f;
    }
    // Translation: -R^T * t.
    for (int row = 0; row < 3; ++row)
    {
        mjtNum v = 0;
        for (int k = 0; k < 3; ++k)
        {
            v += r[k * 3 + row] * kTransMjFromXr[k]; // R^T[row][k] = R[k][row]
        }
        out[12 + row] = static_cast<float>(-v);
    }
    out[12 + 3] = 1.0f;
}

} // namespace mujoco_xr
