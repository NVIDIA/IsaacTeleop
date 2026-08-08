// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The app's only XR<->MuJoCo frame crossing, declared and converted here once;
// the Python side reaches these through the pybind module rather than
// re-deriving them. Rules:
//
//   - Quaternions cross as xyzw (OpenXR, and so Teleop's GRIP_ORIENTATION);
//     MuJoCo is wxyz and viz::Pose3D is a third spelling. Reorder on every
//     crossing, name every variable q_xyzw or q_wxyz, and fill boundary structs
//     field by field.
//   - R_mj_from_xr = Rz(-90deg) * Rx(+90deg). Axis map: XR -Z -> MJ +x,
//     XR +Y -> MJ +z, XR +X -> MJ -y. tests/test_frames.py pins it as: a point
//     1 m in front of the operator at eye height h lands at MuJoCo (+1, 0, h)
//     before the workspace translation.
//   - p_mj = R * p_xr + t;  q_mj = q_mj_from_xr (x) q_xr.
//
// Direction reads by adjacency: p_mj = mj_from_xr_pos(p_xr). Use that `_from_`
// form, never the A_T_B robotics form.

#include <mujoco/mujoco.h>

#include <array>

namespace mujoco_xr
{

// A handedness convention, fixed by the two specs (OpenXR is y-up /
// -z-forward, MuJoCo is REP-103 z-up), so it cannot be wrong at runtime. If a
// scene's static content appears rotated 90 degrees, this is the bug; the ghost
// cannot show it, because the rotation that places it is undone when the
// renderer folds it back into the XR reference space.
//
// Deliberately diverges from
// examples/cloudxr_mujoco_teleop/visualize_poses_mujoco_example.py, which
// applies Rx(+90) only and maps XR-forward to MuJoCo +y, which is not REP-103.
// Do not "fix" this constant to match it.
inline constexpr std::array<double, 4> kQuatMjFromXr = { 0.5, 0.5, -0.5, -0.5 }; // wxyz

// A workspace calibration, routinely wrong, placing static scene content only:
// the ghost goes out through mj_from_xr and back through xr_from_mj, so this
// cancels on it and the shipped ghost-only scene shows nothing of it. Two
// independent terms, and zeroing either is a bug:
//   x = -1.0  operator standoff: the robot base sits ~1 m in front of the
//             operator. Unaffected by the reference space.
//   z = -0.73 floor datum: MuJoCo z=0 is a work surface 0.73 m above the floor.
//             Correct only against a floor-origin reference space, which the
//             session does not ask for -- viz's default origin is the headset's
//             start pose. A scene that adds static content owns re-tuning this
//             for the origin it actually gets.
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
