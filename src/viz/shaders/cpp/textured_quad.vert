// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Two render modes selected by push constant:
//   mode == 0 — fullscreen pass (legacy / window / kXr-no-placement).
//               3-vertex oversized triangle covering NDC [-1, 1].
//               MVP ignored. UVs derived from the same gl_VertexIndex
//               trick as solid_color.vert.
//
//   mode != 0 — 3D placed pass (kXr with QuadLayer::Config::placement_
//               size_meters > 0). 4-vertex triangle strip in local quad
//               space [-0.5, 0.5]; MVP transforms to clip via the
//               eye's view + projection.
//
// One pipeline, one shader, two draw calls (vkCmdDraw with 3 or 4
// verts) selected by the host based on placement config.

#version 450

layout(push_constant) uniform QuadShaderData
{
    mat4 mvp;
    int mode;
} pc;

layout(location = 0) out vec2 v_uv;

void main()
{
    if (pc.mode == 0)
    {
        // Fullscreen oversized triangle.
        //
        // gl_Position.z = 1.0 (Vulkan far plane in [0,1]) — head-locked
        // / fullscreen content has no meaningful 3D position. Writing
        // z = 0 would tell CloudXR everything is at the near plane,
        // which is worse than no depth (reprojection would squash to
        // inches from the user's face). Pinning depth at far makes
        // reprojection a no-op for these pixels — the correct semantic
        // for a head-locked overlay. Pipeline depth compare is
        // LESS_OR_EQUAL so 1.0 ≤ 1.0 (the cleared depth) still passes
        // and fullscreen still renders.
        v_uv = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
        gl_Position = vec4(v_uv * 2.0 - 1.0, 1.0, 1.0);
    }
    else
    {
        // 4-vertex triangle strip: BL, BR, TL, TR in local [-0.5, 0.5]
        // with UV in [0, 1]. MVP transforms to clip.
        const vec2 quad_xy[4] = vec2[](
            vec2(-0.5, -0.5),
            vec2( 0.5, -0.5),
            vec2(-0.5,  0.5),
            vec2( 0.5,  0.5)
        );
        const vec2 quad_uv[4] = vec2[](
            vec2(0.0, 0.0),
            vec2(1.0, 0.0),
            vec2(0.0, 1.0),
            vec2(1.0, 1.0)
        );
        v_uv = quad_uv[gl_VertexIndex];
        gl_Position = pc.mvp * vec4(quad_xy[gl_VertexIndex], 0.0, 1.0);
    }
}
