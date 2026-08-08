// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The welded vertex / index buffers the renderer draws from, built once from
// mjModel.
//
// Normals are computed here, not taken from mjModel: MuJoCo welds an STL's
// vertices and stores one averaged normal per welded vertex (mesh_normalnum ==
// mesh_vertnum, mesh_facenormal == mesh_face), so on a CAD part every crease
// gets a normal smeared across it. Measured on the shipped scene under
// test_ghost.py's own predicate (dot(corner normal, own face normal) <= 0):
// 2138 of Wrist_Roll_SO101's 18474 face corners point away from their own
// face, and 9489 of the STS3215's 57240. Lit one-sided those corners drop to
// scene.frag's 0.35 ambient floor and the part renders as shattered facets, a
// shading bug that looks like a broken mesh. So each face gets its own three
// vertices, and each corner an area-weighted average over the faces round it
// that lie within kCreaseCos.
//
// Indices stay mesh-local with a per-mesh base_vertex, which is what
// vkCmdDrawIndexed's vertexOffset consumes directly; absolute indices would
// need every consumer to undo the folding.
//
// No kNearZ / kFarZ here. The Python app owns the clip planes as one named pair
// reaching VizSessionConfig, the projection and the submitted depth; a second
// definition in C++ drifts and makes compositor reprojection wrong on hardware
// nobody can test here.

#include <mujoco/mujoco.h>

#include <cstdint>
#include <vector>

namespace mujoco_xr
{

// The one directional light, in MuJoCo world space, normalized on upload. The
// half-lambert `ambient` term stays a `const float` in shaders/scene.frag: no
// C++ reads it, so hoisting it would cost a uniform to share one float.
inline constexpr float kLightDirWorld[3] = { 0.35f, -0.25f, -1.0f };

// Faces meeting at less than this angle are smoothed together; anything
// sharper stays a crease. 35 degrees keeps the SO-101 handle's curve smooth
// and its bolt holes crisp.
inline constexpr float kCreaseCos = 0.819f; // cos(35 deg)

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
    std::vector<MeshRange> meshes; // indexed by meshid
};

// Welds every mesh in `m` into one vertex / index pair.
void build_mesh_buffers(const mjModel* m, MeshBuffers* out);

} // namespace mujoco_xr
