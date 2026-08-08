// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Not covered by clang_format_check or the REUSE / copyright-year hooks:
// `.frag` is in neither cmake/ClangFormat.cmake's pattern list nor the
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
// Half-lambert with one hardcoded directional light. Alpha passes through
// straight (unpremultiplied): the background clears to alpha 0 so AR
// passthrough shows behind the scene.

#version 450

layout(location = 0) in vec3 v_normal_w;

layout(set = 0, binding = 0) uniform Eye
{
    mat4 viewproj;
    vec4 light_dir;
} eye;

// Must match scene.vert's block exactly: both stages share one push-constant
// range, so a field here that the vertex shader does not have shifts `color`
// to an offset the host never wrote.
layout(push_constant) uniform PC
{
    mat4 model;
    vec4 color;
} pc;

layout(location = 0) out vec4 out_color;

void main()
{
    vec3 n = normalize(v_normal_w);
    vec3 l = normalize(-eye.light_dir.xyz);
    float diff = max(dot(n, l), 0.0);
    const float ambient = 0.35;
    out_color = vec4(pc.color.rgb * (ambient + (1.0 - ambient) * diff), pc.color.a);
}
