// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Not covered by clang_format_check or the REUSE / copyright-year hooks:
// `.vert` is in neither cmake/ClangFormat.cmake's pattern list nor the
// `files:` regex in .pre-commit-config.yaml. So the SPDX lines above are
// hand-written and must be kept by hand.
//
// Deliberately NOT run through clang-format: it is a C++ formatter and it
// mangles GLSL layout blocks. `clang-format-14 --dry-run -Werror` fails on
// src/viz/shaders/cpp/textured_quad.vert too -- hand-formatted GLSL is the
// established convention here, not an oversight. Since no tool will ever
// arbitrate the shape of these files, this one follows that same precedent
// BY HAND: 4-space indent, opening braces on their own line.
//
// MuJoCo XR scene shader: one pipeline, meshes only. Geometry is in MuJoCo
// world space; eye.viewproj already folds in xr_from_mj and the per-view
// pose/fov handed over by viz (mjvGLCamera is bypassed by design).

#version 450

layout(location = 0) in vec3 in_pos;
layout(location = 1) in vec3 in_normal;

layout(set = 0, binding = 0) uniform Eye
{
    mat4 viewproj;    // P * V * xr_from_mj
    vec4 light_dir;   // world-space travel direction of the one light
} eye;

layout(push_constant) uniform PC
{
    mat4 model;   // world from geom-local (rotation, translation)
    vec4 color;
} pc;

// The ONLY varying. The fragment shader lights with a directional light, which
// needs no world position -- do not add one back "for future point lights"
// until there is a point light.
layout(location = 0) out vec3 v_normal_w;

void main()
{
    vec4 pw = pc.model * vec4(in_pos, 1.0);
    // model's upper 3x3 is a pure rotation (mjvGeom.mat, no scale), so it is
    // its own inverse-transpose and needs no separate normal matrix.
    v_normal_w = mat3(pc.model) * in_normal;
    gl_Position = eye.viewproj * pw;
}
