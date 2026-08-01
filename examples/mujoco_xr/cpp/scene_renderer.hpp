// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// mjvScene -> Vulkan, scene-specific by design: MESH + BOX only (planes are
// skipped -- this is an AR scene and passthrough is the background), one
// pipeline, push constants, one hardcoded directional light, no textures, no
// shadows, no sorting.
//
// View and projection come exclusively from the per-view pose + fov that viz
// hands over in FrameInfo.views; mjvGLCamera is bypassed. mjvCamera exists
// only so mjv_updateScene has a viewpoint for culling / LOD, and it is a
// central free camera precisely so one eye's frustum cannot cull geometry out
// of the other's.
//
// OWNERSHIP (and it is deliberate): C++ owns mjvScene / mjvOption / mjvCamera
// and calls mjv_updateScene; Python owns mjModel / mjData / mj_step. mjvScene
// has no `_address` on the Python side and its `geoms` is a tuple, so it
// cannot be driven from Python at all -- but nothing is lost, because
// mjvScene is a derived view. No authority moves.
//
// THREADING: render() must be called on the same thread as mj_step, after it,
// and mjData is treated as const throughout. A future threaded Python loop
// breaks this SILENTLY -- geometry one step stale reads as jitter, not as a
// race -- which is why it is stated here rather than left implicit.

#include "mesh_buffers.hpp"
#include "render_target.hpp"

#include <mujoco/mujoco.h>
#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <vector>

namespace mujoco_xr
{

// The column-major Vulkan-convention projection for one asymmetric fov
// (angle_left, angle_right, angle_up, angle_down, radians). Exposed on its own
// -- and not only as a renderer method -- so the clip convention can be pinned
// by a test with no GPU, no headset and no VizSession.
std::array<float, 16> projection_from_fov(const std::array<float, 4>& fov_lrud, float near_z, float far_z);

class SceneRenderer
{
public:
    struct Config
    {
        uint32_t width = 0;
        uint32_t height = 0;
        uint32_t view_count = 2;
        // Single-sourced by the Python app and passed in: the SAME pair also
        // goes into VizSessionConfig.xr_near_z / xr_far_z and therefore into
        // XrCompositionLayerDepthInfoKHR. There is no default and no literal
        // anywhere in this module, because a drift between the depth we encode
        // and the range the runtime is told makes compositor reprojection
        // wrong, and the symptom (world-locked geometry swimming under head
        // motion) is only visible on hardware.
        float near_z = 0.0f;
        float far_z = 0.0f;
    };

    SceneRenderer(const BorrowedDevice& dev, const Config& config, const mjModel* model);
    ~SceneRenderer();

    SceneRenderer(const SceneRenderer&) = delete;
    SceneRenderer& operator=(const SceneRenderer&) = delete;

    // mjv_updateScene, exactly once per frame. Returns the geom count.
    int update_scene(const mjModel* model, mjData* data);

    // Decor geoms appended after update_scene, drawn last so they land over
    // the robot. Used for controller markers -- display only, no control
    // authority.
    void clear_markers();
    void add_marker(const std::array<double, 3>& pos_mj,
                    const std::array<double, 4>& quat_mj_wxyz,
                    const std::array<double, 3>& half_extent,
                    const std::array<float, 4>& rgba);

    // Renders every view in one queue submit and blocks until the readback
    // copies have retired, so the CUDA pointers are safe to hand to
    // ProjectionLayer.submit() the moment this returns.
    //
    // poses_xyz_qwxyz: view_count * 7 floats -- position (x, y, z) then
    //   orientation (w, x, y, z), matching viz.Pose3D's spelling.
    // fovs_lrud: view_count * 4 floats -- angle_left, angle_right, angle_up,
    //   angle_down, in radians, matching viz.Fov's field order.
    void render(const std::vector<float>& poses_xyz_qwxyz, const std::vector<float>& fovs_lrud);

    // The column-major projection actually used for `view` on the last
    // render(). Exposed so the app can assert the clip convention per frame.
    const std::array<float, 16>& projection(int view) const;

    const ViewTarget& view_target(int view) const;
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
    void create_pipeline();
    void upload_geometry(const mjModel* model);
    void create_uniforms();
    void destroy();

    BorrowedDevice dev_;
    Config config_;

    VkRenderPass render_pass_ = VK_NULL_HANDLE;
    VkDescriptorSetLayout dsl_ = VK_NULL_HANDLE;
    VkDescriptorPool descriptor_pool_ = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;
    VkCommandPool command_pool_ = VK_NULL_HANDLE;
    VkCommandBuffer command_buffer_ = VK_NULL_HANDLE;
    VkFence fence_ = VK_NULL_HANDLE;

    std::vector<VkDescriptorSet> descriptor_sets_;
    std::vector<VkBuffer> ubos_;
    std::vector<VkDeviceMemory> ubo_memory_;
    std::vector<void*> ubo_mapped_;
    std::vector<ViewTarget> view_targets_;
    std::vector<std::array<float, 16>> projections_;

    VkBuffer vertex_buffer_ = VK_NULL_HANDLE;
    VkDeviceMemory vertex_memory_ = VK_NULL_HANDLE;
    VkBuffer index_buffer_ = VK_NULL_HANDLE;
    VkDeviceMemory index_memory_ = VK_NULL_HANDLE;

    MeshRange box_range_;
    std::vector<MeshRange> mesh_ranges_;
    float xr_from_mj_[16] = { 0 };

    mjvScene scene_{};
    mjvOption scene_option_{};
    mjvCamera camera_{};
    bool scene_made_ = false;
    int base_ngeom_ = 0; // geom count from mjv_updateScene, before markers
};

} // namespace mujoco_xr
