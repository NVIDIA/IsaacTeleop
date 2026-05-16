// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Samples color + depth and writes both. gl_FragDepth ensures
// other layers (rendered after) Z-test against the projection content
// — that's the core ProjectionLayer feature. The fragment shader is
// dispatched per-view; the descriptor set is bound to the per-eye
// (color, depth) pair.

#version 450

layout(set = 0, binding = 0) uniform sampler2D u_color;
layout(set = 0, binding = 1) uniform sampler2D u_depth;

layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 out_color;

void main()
{
    out_color = texture(u_color, v_uv);
    gl_FragDepth = texture(u_depth, v_uv).r;
}
