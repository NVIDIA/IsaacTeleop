// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "scene_renderer.hpp"

#include "frames.hpp"
#include "glcamera.hpp"

#include <array>
#include <cuda_gl_interop.h>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace mujoco_xr
{

namespace
{

// Not a knob: overflowing it is a hard error, and 20k is ~30x a tabletop scene.
constexpr int kMaxGeom = 20000;

// OpenXR view space: -Z forward, +Y up.
constexpr std::array<double, 3> kXrForward = { 0.0, 0.0, -1.0 };
constexpr std::array<double, 3> kXrUp = { 0.0, 1.0, 0.0 };

void check_cuda(cudaError_t err, const char* what)
{
    if (err != cudaSuccess)
    {
        throw std::runtime_error(std::string("mujoco_xr: ") + what + " failed: " + cudaGetErrorString(err));
    }
}

// viz's VkContext::init() already cudaSetDevice'd the card matching its Vulkan
// device, so "viz's GPU" is just the current CUDA device. The GL context is
// made independently, and nothing makes it land on the same card.
void require_gl_on_viz_device()
{
    int cuda_device = -1;
    check_cuda(cudaGetDevice(&cuda_device), "cudaGetDevice");

    unsigned int count = 0;
    int gl_devices[8] = { 0 };
    const cudaError_t err = cudaGLGetDevices(&count, gl_devices, 8, cudaGLDeviceListAll);
    if (err != cudaSuccess || count == 0)
    {
        throw std::runtime_error(
            std::string("mujoco_xr: the current OpenGL context is on no CUDA-capable device (") + cudaGetErrorString(err) +
            "). Create it with mujoco.GLContext BEFORE the renderer, on this thread, with MUJOCO_GL=egl.");
    }
    for (unsigned int i = 0; i < count; ++i)
    {
        if (gl_devices[i] == cuda_device)
        {
            return;
        }
    }
    throw std::runtime_error(
        "mujoco_xr: the OpenGL context is on CUDA device " + std::to_string(gl_devices[0]) + " but viz is on device " +
        std::to_string(cuda_device) +
        ". Set MUJOCO_EGL_DEVICE_ID to viz's GPU; a cross-device pixel-pack buffer cannot be imported.");
}

// A direction from XR into MuJoCo world: rotation only, no workspace offset.
std::array<double, 3> mj_from_xr_dir(const std::array<double, 4>& q_mj, const std::array<double, 3>& v_xr)
{
    std::array<double, 3> out{};
    mju_rotVecQuat(out.data(), v_xr.data(), q_mj.data());
    return out;
}

} // namespace

SceneRenderer::SceneRenderer(const Config& config, const mjModel* model) : config_(config)
{
    if (model == nullptr)
    {
        throw std::invalid_argument("mujoco_xr: null mjModel*");
    }
    if (config_.width == 0 || config_.height == 0 || config_.view_count == 0)
    {
        throw std::invalid_argument("mujoco_xr: renderer needs a non-empty size and at least one view");
    }
    // Validates near/far up front, on a fov that is certainly non-degenerate.
    (void)frustum_from_fov({ -0.5f, 0.5f, 0.5f, -0.5f }, config_.near_z, config_.far_z);

    gl::load();
    require_gl_on_viz_device();

    mjv_defaultOption(&scene_option_);
    mjv_defaultFreeCamera(model, &camera_);
    mjv_makeScene(model, &scene_, kMaxGeom);
    scene_made_ = true;
    // Each eye is drawn on its own, into the whole offscreen buffer.
    scene_.stereo = mjSTEREO_NONE;

    mjr_defaultContext(&context_);
    mjr_makeContext(model, &context_, mjFONTSCALE_100);
    context_made_ = true;
    // Overrides whatever <visual><global offwidth/offheight> the scene declared.
    mjr_resizeOffscreen(static_cast<int>(config_.width), static_cast<int>(config_.height), &context_);
    if (context_.offWidth != static_cast<int>(config_.width) || context_.offHeight != static_cast<int>(config_.height))
    {
        throw std::runtime_error("mujoco_xr: mjr_resizeOffscreen did not take; the GL context is too small or lost");
    }
    if (context_.offSamples != 0)
    {
        throw std::runtime_error(
            "mujoco_xr: model.vis.quality.offsamples must be 0. Multisample renderbuffers cannot be blitted with a "
            "y flip in one step, and MuJoCo resolves them only inside mjr_readPixels, which this path does not call.");
    }
    mjr_setBuffer(mjFB_OFFSCREEN, &context_);
    if (context_.currentBuffer != mjFB_OFFSCREEN)
    {
        throw std::runtime_error("mujoco_xr: the offscreen framebuffer is unavailable in this OpenGL context");
    }

    readback_.create(config_.width, config_.height, config_.view_count, context_.offFBO);
    cameras_.resize(config_.view_count);
}

SceneRenderer::~SceneRenderer()
{
    destroy();
}

void SceneRenderer::destroy()
{
    readback_.destroy();
    if (context_made_)
    {
        mjr_freeContext(&context_);
        context_made_ = false;
    }
    if (scene_made_)
    {
        mjv_freeScene(&scene_);
        scene_made_ = false;
    }
}

int SceneRenderer::update_scene(const mjModel* model, mjData* data)
{
    if (model == nullptr || data == nullptr)
    {
        throw std::invalid_argument("mujoco_xr: update_scene got a null mjModel* / mjData*");
    }
    mjv_updateScene(model, data, &scene_option_, nullptr, &camera_, mjCAT_ALL, &scene_);
    return scene_.ngeom;
}

std::vector<float> SceneRenderer::frustum(int view) const
{
    if (view < 0 || static_cast<uint32_t>(view) >= config_.view_count)
    {
        throw std::out_of_range("mujoco_xr: view index out of range");
    }
    const mjvGLCamera& c = cameras_[static_cast<size_t>(view)];
    return { c.frustum_center, c.frustum_width, c.frustum_bottom, c.frustum_top, c.frustum_near, c.frustum_far };
}

void SceneRenderer::render(const std::vector<float>& poses_xyz_qwxyz, const std::vector<float>& fovs_lrud)
{
    const size_t n = config_.view_count;
    if (poses_xyz_qwxyz.size() != n * 7 || fovs_lrud.size() != n * 4)
    {
        throw std::invalid_argument(
            "mujoco_xr: render() expects view_count*7 pose floats and view_count*4 fov floats; the renderer's "
            "view_count must match len(FrameInfo.views)");
    }

    const mjrRect viewport{ 0, 0, static_cast<int>(config_.width), static_cast<int>(config_.height) };

    for (size_t v = 0; v < n; ++v)
    {
        const float* pose = poses_xyz_qwxyz.data() + v * 7;
        const float* fov = fovs_lrud.data() + v * 4;

        // The eye crosses into MuJoCo world, not the geometry the other way:
        // mjr_render draws MuJoCo world and takes a camera, not a view matrix.
        const std::array<double, 4> q_xyzw = { pose[4], pose[5], pose[6], pose[3] };
        const std::array<double, 4> q_mj = mj_from_xr_quat(q_xyzw);
        const std::array<double, 3> p_mj = mj_from_xr_pos({ pose[0], pose[1], pose[2] });
        const std::array<double, 3> forward = mj_from_xr_dir(q_mj, kXrForward);
        const std::array<double, 3> up = mj_from_xr_dir(q_mj, kXrUp);

        const Frustum f = frustum_from_fov({ fov[0], fov[1], fov[2], fov[3] }, config_.near_z, config_.far_z);

        mjvGLCamera& cam = cameras_[v];
        cam = mjvGLCamera{};
        for (int i = 0; i < 3; ++i)
        {
            cam.pos[i] = static_cast<float>(p_mj[i]);
            cam.forward[i] = static_cast<float>(forward[i]);
            cam.up[i] = static_cast<float>(up[i]);
        }
        cam.frustum_center = f.center;
        cam.frustum_width = f.half_width;
        cam.frustum_bottom = f.bottom;
        cam.frustum_top = f.top;
        cam.frustum_near = f.near_z;
        cam.frustum_far = f.far_z;
        cam.orthographic = 0;

        // mjv_updateScene wrote both cameras from mjvCamera; overwrite them
        // after it, and both, because mjSTEREO_NONE renders their average.
        // Lights are NOT overwritten with them: mjv_updateScene already baked
        // the headlight from camera_, so it stays a world-fixed directional
        // light rather than following the eye.
        scene_.camera[0] = cam;
        scene_.camera[1] = cam;

        mjr_render(viewport, &scene_, &context_);
        readback_.capture(static_cast<uint32_t>(v), context_.offFBO);
    }

    readback_.map();
}

} // namespace mujoco_xr
