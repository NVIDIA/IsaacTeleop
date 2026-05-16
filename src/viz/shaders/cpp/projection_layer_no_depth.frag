// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// No-depth variant: writes color only, lets the rasterizer's z = 1.0
// (from the vertex shader) flow through. The pipeline's
// depthWriteEnable = VK_FALSE so this content sits at far without
// affecting subsequent layers' depth test. Used when ProjectionLayer
// is configured without a depth buffer (Config::depth_format == nullopt).

#version 450

layout(set = 0, binding = 0) uniform sampler2D u_color;
// Binding 1 is allocated (descriptor layout stays uniform across both
// pipeline variants) but unused here.

layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 out_color;

void main()
{
    out_color = texture(u_color, v_uv);
}
