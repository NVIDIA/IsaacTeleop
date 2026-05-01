// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Samples a combined image sampler at descriptor binding 0. Used by
// QuadLayer (ships in M3b) to display a CUDA-fed texture as a quad.

#version 450

layout(set = 0, binding = 0) uniform sampler2D u_texture;

layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 out_color;

void main()
{
    out_color = texture(u_texture, v_uv);
}
