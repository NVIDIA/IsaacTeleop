// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// MuJoCo's own renderer, driven once per eye into an offscreen framebuffer that
// Readback turns into CUDA pointers. Shading, materials, lights and shadows all
// stay MuJoCo's -- none of it lives here.
//
// The OpenGL context is NOT created here: `mujoco.GLContext` makes it, and it
// must be current on this thread and on viz's GPU before the constructor runs.
// The constructor checks the GPU rather than render into another card's memory.
//
// C++ owns mjvScene/mjvOption/mjvCamera; Python owns mjModel/mjData/mj_step.
// render() runs on the mj_step thread, after it, and treats mjData as const.

#include "gl_readback.hpp"

#include <mujoco/mujoco.h>

#include <cstdint>
#include <vector>

namespace mujoco_xr
{

class SceneRenderer
{
public:
    struct Config
    {
        uint32_t width = 0;
        uint32_t height = 0;
        // A field because the render loop reads it, not because mono works.
        uint32_t view_count = 2;
        // No default, and no near/far literal anywhere in cpp/: this pair must
        // equal VizSessionConfig.xr_near_z / xr_far_z, or the runtime reprojects
        // the submitted depth against the wrong range.
        float near_z = 0.0f;
        float far_z = 0.0f;
    };

    SceneRenderer(const Config& config, const mjModel* model);
    ~SceneRenderer();

    SceneRenderer(const SceneRenderer&) = delete;
    SceneRenderer& operator=(const SceneRenderer&) = delete;

    // mjv_updateScene, exactly once per frame. Returns the geom count.
    int update_scene(const mjModel* model, mjData* data);

    // Draws every view and leaves the CUDA pointers mapped, ready for
    // ProjectionLayer.submit() the moment this returns. `poses_xyz_qwxyz` is
    // view_count*7 (position then w,x,y,z, viz.Pose3D's spelling) and
    // `fovs_lrud` view_count*4 radians in viz.Fov's field order.
    void render(const std::vector<float>& poses_xyz_qwxyz, const std::vector<float>& fovs_lrud);

    // Last render()'s frustum for `view`, as (center, half_width, bottom, top,
    // near, far), so the app can assert the convention per frame.
    std::vector<float> frustum(int view) const;

    const Readback& readback() const
    {
        return readback_;
    }
    uint32_t view_count() const
    {
        return config_.view_count;
    }
    int ngeom() const
    {
        return scene_.ngeom;
    }
    int maxgeom() const
    {
        return scene_.maxgeom;
    }

private:
    void destroy();

    Config config_;
    Readback readback_;

    mjvScene scene_{};
    mjvOption scene_option_{};
    mjvCamera camera_{};
    mjrContext context_{};
    bool scene_made_ = false;
    bool context_made_ = false;

    std::vector<mjvGLCamera> cameras_;
};

} // namespace mujoco_xr
