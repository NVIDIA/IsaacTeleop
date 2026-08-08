// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "mesh_buffers.hpp"

#include <array>
#include <cmath>
#include <cstring>
#include <vector>

namespace mujoco_xr
{

void build_mesh_buffers(const mjModel* m, MeshBuffers* out)
{
    std::vector<Vertex>& verts = out->verts;
    std::vector<uint32_t>& indices = out->indices;
    verts.clear();
    indices.clear();

    // Meshes: one vertex per FACE CORNER, carrying a normal computed here.
    // See the header for why mjModel's own normals cannot be used.
    out->meshes.assign(static_cast<size_t>(m->nmesh), MeshRange());
    std::vector<std::array<float, 3>> face_normal;
    std::vector<float> face_area;
    std::vector<std::vector<int>> vertex_faces;
    for (int mesh = 0; mesh < m->nmesh; ++mesh)
    {
        MeshRange& range = out->meshes[static_cast<size_t>(mesh)];
        range.base_vertex = static_cast<int32_t>(verts.size());
        range.first_index = static_cast<uint32_t>(indices.size());
        const float* mverts = m->mesh_vert + 3 * m->mesh_vertadr[mesh];
        const int* mfaces = m->mesh_face + 3 * m->mesh_faceadr[mesh];
        const int facenum = m->mesh_facenum[mesh];

        // Pass 1: the geometric normal and area of every face, and which faces
        // touch each vertex.
        face_normal.assign(static_cast<size_t>(facenum), { 0.0f, 0.0f, 0.0f });
        face_area.assign(static_cast<size_t>(facenum), 0.0f);
        vertex_faces.assign(static_cast<size_t>(m->mesh_vertnum[mesh]), {});
        for (int f = 0; f < facenum; ++f)
        {
            const int* face = mfaces + 3 * f;
            const float* p[3] = { mverts + 3 * face[0], mverts + 3 * face[1], mverts + 3 * face[2] };
            const float e1[3] = { p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2] };
            const float e2[3] = { p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2] };
            std::array<float, 3> n = { e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2],
                                       e1[0] * e2[1] - e1[1] * e2[0] };
            const float len = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
            face_area[static_cast<size_t>(f)] = 0.5f * len;
            if (len > 0.0f)
            {
                n[0] /= len;
                n[1] /= len;
                n[2] /= len;
            }
            face_normal[static_cast<size_t>(f)] = n;
            for (int k = 0; k < 3; ++k)
            {
                vertex_faces[static_cast<size_t>(face[k])].push_back(f);
            }
        }

        // Pass 2: one vertex per corner, its normal area-averaged over the
        // faces round that vertex that lie WITHIN the crease angle of this
        // one. Curved surfaces stay smooth; an edge sharper than the threshold
        // keeps both of its faces flat.
        uint32_t local_count = 0;
        for (int f = 0; f < facenum; ++f)
        {
            const int* face = mfaces + 3 * f;
            const std::array<float, 3>& fn = face_normal[static_cast<size_t>(f)];
            for (int k = 0; k < 3; ++k)
            {
                float acc[3] = { 0.0f, 0.0f, 0.0f };
                for (int g : vertex_faces[static_cast<size_t>(face[k])])
                {
                    const std::array<float, 3>& gn = face_normal[static_cast<size_t>(g)];
                    const float cosine = fn[0] * gn[0] + fn[1] * gn[1] + fn[2] * gn[2];
                    if (cosine >= kCreaseCos)
                    {
                        const float w = face_area[static_cast<size_t>(g)];
                        acc[0] += gn[0] * w;
                        acc[1] += gn[1] * w;
                        acc[2] += gn[2] * w;
                    }
                }
                const float len = std::sqrt(acc[0] * acc[0] + acc[1] * acc[1] + acc[2] * acc[2]);
                Vertex v;
                std::memcpy(v.pos, mverts + 3 * face[k], sizeof(v.pos));
                for (int c = 0; c < 3; ++c)
                {
                    // A zero sum needs the face's own normal: it means every
                    // contribution cancelled, not that the surface has none.
                    v.normal[c] = len > 0.0f ? acc[c] / len : fn[static_cast<size_t>(c)];
                }
                verts.push_back(v);
                indices.push_back(local_count++);
            }
        }
        range.index_count = static_cast<uint32_t>(indices.size()) - range.first_index;
    }
}

} // namespace mujoco_xr
