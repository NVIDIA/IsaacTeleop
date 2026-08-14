// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// pybind11 entry point for `mujoco_xr._mujoco_xr`.
//
// Nothing typed crosses this boundary in either direction. viz::Pose3D / Fov
// are registered in `_viz` and not castable here (this module links no viz
// target), so poses and fovs cross as flat float arrays; mjModel / mjData cross
// as integer addresses, Python owning them and C++ owning mjvScene / mjrContext.

#include "frames.hpp"
#include "glcamera.hpp"
#include "scene_renderer.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace mujoco_xr
{
namespace
{

namespace py = pybind11;

// A non-owning view of one CUDA-mapped pack buffer, shaped for viz's
// `cuda_array_to_viz_buffer`: kRGBA8 -> "|u1" (H, W, 4), kD32F -> "<f4" (H, W),
// strides=None for the tight rows glReadPixels writes. Made fresh per frame.
struct CudaImageView
{
    uintptr_t ptr = 0;
    uint32_t width = 0;
    uint32_t height = 0;
    bool is_depth = false;

    py::dict cuda_array_interface() const
    {
        py::dict d;
        if (is_depth)
        {
            d["shape"] = py::make_tuple(height, width);
            d["typestr"] = "<f4";
        }
        else
        {
            d["shape"] = py::make_tuple(height, width, 4);
            d["typestr"] = "|u1";
        }
        d["data"] = py::make_tuple(ptr, /*read_only=*/false);
        d["strides"] = py::none();
        d["version"] = 3;
        return d;
    }
};

// Thin owner, so Python constructs the renderer from plain integers.
class PyRenderer
{
public:
    PyRenderer(uint32_t width, uint32_t height, uint32_t view_count, float near_z, float far_z, uintptr_t model_address)
    {
        SceneRenderer::Config cfg;
        cfg.width = width;
        cfg.height = height;
        cfg.view_count = view_count;
        cfg.near_z = near_z;
        cfg.far_z = far_z;
        renderer_ = std::make_unique<SceneRenderer>(cfg, reinterpret_cast<const mjModel*>(model_address));
    }

    SceneRenderer& get()
    {
        if (!renderer_)
        {
            throw std::runtime_error("mujoco_xr: renderer has been closed");
        }
        return *renderer_;
    }

    void close()
    {
        renderer_.reset();
    }

private:
    std::unique_ptr<SceneRenderer> renderer_;
};

CudaImageView image_view(SceneRenderer& r, int view, bool is_depth)
{
    if (view < 0 || static_cast<uint32_t>(view) >= r.view_count())
    {
        throw std::out_of_range("mujoco_xr: view index out of range");
    }
    const Readback& rb = r.readback();
    const auto index = static_cast<uint32_t>(view);
    void* ptr = is_depth ? rb.depth_ptr(index) : rb.color_ptr(index);
    return CudaImageView{ reinterpret_cast<uintptr_t>(ptr), rb.width(), rb.height(), is_depth };
}

} // namespace
} // namespace mujoco_xr

PYBIND11_MODULE(_mujoco_xr, m)
{
    namespace py = pybind11;
    using namespace pybind11::literals;

    m.doc() = "MuJoCo's OpenGL renderer, read back into CUDA for Isaac Teleop's Televiz ProjectionLayer.";

    m.def(
        "mujoco_version", []() { return std::string(mj_versionString()); },
        "The libmujoco this extension is linked against, as reported at runtime. Compare with "
        "mujoco.mj_versionString() -- they MUST be equal, and they are only equal because there is exactly one "
        "libmujoco loaded in the process.");

    // ── Frames ────────────────────────────────────────────────────────────
    // Exposed rather than reimplemented, so frames.hpp stays the one definition.

    m.def(
        "mj_from_xr_pos", [](std::array<double, 3> p_xr) { return mujoco_xr::mj_from_xr_pos(p_xr); }, "p_xr"_a,
        "XR reference-space point (metres, Y-up) -> MuJoCo world point (Z-up). Applies both the handedness "
        "rotation and the workspace translation.");

    m.def(
        "mj_from_xr_quat", [](std::array<double, 4> q_xyzw) { return mujoco_xr::mj_from_xr_quat(q_xyzw); }, "q_xyzw"_a,
        "XR orientation as xyzw (the order OpenXR and Teleop's GRIP_ORIENTATION use) -> MuJoCo world "
        "orientation as wxyz. The ONLY quaternion crossing in the app.");

    // SCREAMING_CASE attributes, not getters: a snake_case getter would put
    // `quat_mj_from_xr` beside `mj_from_xr_quat`, with only word order telling a
    // constant from a transform.
    m.attr("QUAT_MJ_FROM_XR") = py::tuple(py::cast(mujoco_xr::kQuatMjFromXr));
    m.attr("TRANS_MJ_FROM_XR") = py::tuple(py::cast(mujoco_xr::kTransMjFromXr));

    // ── Projection ────────────────────────────────────────────────────────

    m.def(
        "frustum_from_fov",
        [](std::array<float, 4> fov_lrud, float near_z, float far_z)
        {
            const mujoco_xr::Frustum f = mujoco_xr::frustum_from_fov(fov_lrud, near_z, far_z);
            return std::vector<float>{ f.center, f.half_width, f.bottom, f.top, f.near_z, f.far_z };
        },
        "fov_lrud"_a, "near_z"_a, "far_z"_a,
        "The mjvGLCamera frustum fields for one asymmetric fov (angle_left, angle_right, angle_up, angle_down) "
        "in radians, as (center, half_width, bottom, top, near, far). Same code path the renderer uses; exposed "
        "so the convention is testable without a GPU. Raises ValueError on a degenerate fov or a bad near/far.");

    m.def(
        "submitted_depth",
        [](float distance, float near_z, float far_z) { return mujoco_xr::submitted_depth(distance, near_z, far_z); },
        "distance"_a, "near_z"_a, "far_z"_a,
        "What a view-space distance ahead of the eye becomes in the depth buffer handed to "
        "ProjectionLayer.submit(): standard Z, near -> 0, far -> 1. MuJoCo's renderer writes the reverse; "
        "shaders/readback inverts it.");

    // ── Renderer ──────────────────────────────────────────────────────────

    py::class_<mujoco_xr::CudaImageView>(m, "CudaImageView",
                                         R"doc(
Non-owning CUDA view of one of the renderer's pixel-pack buffers.

Exposes ``__cuda_array_interface__``, which is all
``isaacteleop.viz.ProjectionLayer.submit()`` needs. Do NOT hold one past the
frame it came from, and never past ``Renderer.close()``: the memory belongs to
the renderer and is unmapped on the next ``render()``.
)doc")
        .def_property_readonly("__cuda_array_interface__", &mujoco_xr::CudaImageView::cuda_array_interface);

    py::class_<mujoco_xr::PyRenderer>(m, "Renderer",
                                      R"doc(
MuJoCo's OpenGL renderer, read back into CUDA-visible colour + depth buffers.

An OpenGL context must be current on this thread BEFORE construction, on the
same GPU viz chose (``mujoco.GLContext``; set ``MUJOCO_EGL_DEVICE_ID`` if the
machine has more than one card). The constructor checks this and raises rather
than render into another card's memory.

Per frame, in this order and on ONE thread::

    info = session.begin_frame()
    if info.should_render:
        mujoco.mj_step(model, data)          # Python owns the simulation
        renderer.update_scene(m_addr, d_addr)
        renderer.render(poses, fovs)         # poses/fovs from info.views
        layer.submit(renderer.color(0), renderer.depth(0), ...)
    session.end_frame()
)doc")
        .def(py::init<uint32_t, uint32_t, uint32_t, float, float, uintptr_t>(), "width"_a, "height"_a, "view_count"_a,
             "near_z"_a, "far_z"_a, "model_address"_a,
             "`model_address` is mujoco.MjModel._address. No Vulkan handles: this renderer reaches viz through "
             "CUDA alone, and finds viz's GPU as the process's current CUDA device.")
        .def(
            "update_scene",
            [](mujoco_xr::PyRenderer& self, uintptr_t model_address, uintptr_t data_address)
            {
                return self.get().update_scene(
                    reinterpret_cast<const mjModel*>(model_address), reinterpret_cast<mjData*>(data_address));
            },
            "model_address"_a, "data_address"_a,
            "One mjv_updateScene for the frame. Call AFTER mj_step, on the same thread. mjData is treated as "
            "const. Returns the geom count.")
        .def(
            "render",
            [](mujoco_xr::PyRenderer& self, std::vector<float> poses_xyz_qwxyz, std::vector<float> fovs_lrud)
            {
                // No gil_scoped_release: this all runs on the GL context bound
                // to THIS thread, and releasing the GIL would let another
                // thread issue GL on a context it does not hold.
                self.get().render(poses_xyz_qwxyz, fovs_lrud);
            },
            "poses_xyz_qwxyz"_a, "fovs_lrud"_a,
            "Render every view. `poses_xyz_qwxyz` is view_count*7 floats (x, y, z, qw, qx, qy, qz) and "
            "`fovs_lrud` is view_count*4 (angle_left, angle_right, angle_up, angle_down) -- flatten them from "
            "FrameInfo.views.")
        .def(
            "frustum", [](mujoco_xr::PyRenderer& self, int view) { return self.get().frustum(view); }, "view"_a,
            "The mjvGLCamera frustum used for `view` on the last render(), as (center, half_width, bottom, top, "
            "near, far), so the caller can assert the convention per frame.")
        .def(
            "color",
            [](mujoco_xr::PyRenderer& self, int view)
            { return mujoco_xr::image_view(self.get(), view, /*is_depth=*/false); },
            // keep_alive<0, 1>: the view is a bare device pointer into the
            // Renderer's buffers, so a caller who keeps `buf = renderer.color(0)`
            // and drops `renderer` would use-after-free at submit time.
            py::keep_alive<0, 1>(), "view"_a,
            "RGBA8 colour for `view` as a CudaImageView. Valid until the next render().")
        .def(
            "depth",
            [](mujoco_xr::PyRenderer& self, int view)
            { return mujoco_xr::image_view(self.get(), view, /*is_depth=*/true); },
            py::keep_alive<0, 1>(), "view"_a, // see color() above
            "float32 depth for `view` as a CudaImageView, standard Z: near -> 0.0, far -> 1.0. Valid until the "
            "next render().")
        .def_property_readonly("view_count", [](mujoco_xr::PyRenderer& self) { return self.get().view_count(); })
        .def_property_readonly("ngeom", [](mujoco_xr::PyRenderer& self) { return self.get().ngeom(); })
        .def_property_readonly("maxgeom", [](mujoco_xr::PyRenderer& self) { return self.get().maxgeom(); })
        .def("close", &mujoco_xr::PyRenderer::close,
             "Release the OpenGL and CUDA resources. Must happen while the GL context is still current, so "
             "BEFORE mujoco.GLContext.free().");
}
