// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Fullscreen oversized triangle covering NDC [-1, 1]. Same gl_VertexIndex
// UV trick as textured_quad.vert's mode == 0 branch.
//
// gl_Position.z is INERT for both ProjectionLayer pipeline variants:
//   * pipeline_with_depth: the frag shader writes gl_FragDepth from
//     the sampled depth texture, overriding the rasterized z for both
//     the depth test and the depth write.
//   * pipeline_no_depth: depthWriteEnable = false, so the rasterized z
//     never reaches the depth buffer. The depth attachment keeps the
//     clear value (1.0 = far), which is the right semantic for
//     "no depth → reproject as far-plane background."
//
// We still set z = 1.0 (far) as the safe default — matches QuadLayer's
// fullscreen convention, and guards against accidentally enabling
// depth write on the no_depth pipeline later (which would otherwise
// place the layer "right at the user's face" and break reprojection).

#version 450

layout(location = 0) out vec2 v_uv;

void main()
{
    v_uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
    gl_Position = vec4(v_uv * 2.0 - 1.0, 1.0, 1.0);
}
