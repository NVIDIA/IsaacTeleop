// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Fullscreen-quad vertex shader that also forwards UVs for sampling.
// Uses the same gl_VertexIndex trick as solid_color.vert: 3 vertices
// → covers the screen, no vertex buffer needed.

#version 450

layout(location = 0) out vec2 v_uv;

void main()
{
    v_uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
    gl_Position = vec4(v_uv * 2.0 - 1.0, 0.0, 1.0);
}
