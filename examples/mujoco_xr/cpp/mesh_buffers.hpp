// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The welded vertex / index buffers the renderer draws from, built once from
// mjModel.
//
// Meshes are de-indexed at load by welding unique (vertex, normal) index
// pairs, because mesh_facenormal indexes normals separately from mesh_face
// and a GPU vertex must carry both.
//
// Indices stay MESH-LOCAL with a per-mesh base_vertex, rather than absolute.
// That is what vkCmdDrawIndexed's vertexOffset consumes directly. Absolute
// indices would be arithmetically identical (the max welded index is bounded
// by 3*nmeshface, far inside uint32) but would need every consumer to undo
// the folding.
//
// NOTE there is no kNearZ / kFarZ here. The clip planes are owned by the
// Python app as a single named pair reaching VizSessionConfig, the renderer's
// projection and the submitted depth; a second definition in C++ is exactly
// the drift that makes compositor reprojection wrong on hardware nobody can
// test here.

#include <mujoco/mujoco.h>

#include <cstdint>
#include <vector>

namespace mujoco_xr
{

// The one directional light, in MuJoCo world space, normalized on upload.
// The half-lambert `ambient` term is deliberately NOT here: no C++ code reads
// it, so hoisting it would mean a uniform plus a plumbing path to share one
// float. It stays a `const float` inside shaders/scene.frag.
inline constexpr float kLightDirWorld[3] = { 0.35f, -0.25f, -1.0f };

struct Vertex
{
    float pos[3];
    float normal[3];
};

struct MeshRange
{
    int32_t base_vertex = 0;
    uint32_t first_index = 0;
    uint32_t index_count = 0;
};

struct MeshBuffers
{
    std::vector<Vertex> verts;
    std::vector<uint32_t> indices; // mesh-local: add base_vertex to deref
    MeshRange box; // unit box, half-extent 1
    std::vector<MeshRange> meshes; // indexed by meshid
};

// Welds every mesh in `m` plus the unit box into one vertex / index pair.
void build_mesh_buffers(const mjModel* m, MeshBuffers* out);

} // namespace mujoco_xr
