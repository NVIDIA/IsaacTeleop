// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// pybind11 entry point for `mujoco_xr._mujoco_xr`.
//
// Nothing viz-typed crosses this boundary: viz::Pose3D / viz::Fov / ViewInfo
// are registered in the `_viz` module and are not castable here, because this
// module links no viz target. Poses and fovs cross as plain float arrays,
// decomposed on the Python side.
//
// Likewise nothing MuJoCo-typed crosses it: Python owns mjModel / mjData /
// mj_step and passes their addresses as integers; C++ owns mjvScene /
// mjvOption / mjvCamera and calls mjv_updateScene.

#include "frames.hpp"
#include "render_target.hpp"
#include "scene_renderer.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace mujoco_xr
{
namespace
{

namespace py = pybind11;

// A view onto one of the renderer's CUDA-visible staging buffers, shaped for
// viz's `cuda_array_to_viz_buffer` helper. That helper wants:
//   kRGBA8 -> typestr "|u1", shape (H, W, 4)
//   kD32F  -> typestr "<f4", shape (H, W)
// and accepts strides=None for tightly-packed rows, which ours always are.
//
// NON-OWNING: the pointer belongs to the SceneRenderer. Keeping one of these
// past the renderer's lifetime is a dangling read, which is why they are
// produced fresh per frame rather than cached on the Python side.
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
        d["strides"] = py::none(); // tightly packed, C-contiguous
        d["version"] = 3;
        return d;
    }
};

// Thin owner so Python constructs the renderer with plain integers and never
// sees a Vulkan or a MuJoCo type.
class PyRenderer
{
public:
    PyRenderer(uintptr_t vk_physical_device,
               uintptr_t vk_device,
               uint32_t vk_queue_family_index,
               uint32_t width,
               uint32_t height,
               uint32_t view_count,
               float near_z,
               float far_z,
               uintptr_t model_address)
    {
        const BorrowedDevice dev = borrow_device(vk_physical_device, vk_device, vk_queue_family_index);
        SceneRenderer::Config cfg;
        cfg.width = width;
        cfg.height = height;
        cfg.view_count = view_count;
        cfg.near_z = near_z;
        cfg.far_z = far_z;
        renderer_ = std::make_unique<SceneRenderer>(dev, cfg, reinterpret_cast<const mjModel*>(model_address));
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

} // namespace
} // namespace mujoco_xr

PYBIND11_MODULE(_mujoco_xr, m)
{
    namespace py = pybind11;
    using namespace pybind11::literals;

    m.doc() = "MuJoCo -> Vulkan renderer for Isaac Teleop's Televiz ProjectionLayer.";

    m.def(
        "mujoco_version", []() { return std::string(mj_versionString()); },
        "The libmujoco this extension is linked against, as reported at runtime. Compare with "
        "mujoco.mj_versionString() -- they MUST be equal, and they are only equal because there is "
        "exactly one libmujoco loaded in the process.");

    // ── Frames ────────────────────────────────────────────────────────────
    // Exposed rather than reimplemented in Python: kQuatMjFromXr and
    // kTransMjFromXr have exactly one definition (frames.hpp) and the Python
    // app, the renderer and tests/test_frames.py all read that one.

    m.def(
        "mj_from_xr_pos", [](std::array<double, 3> p_xr) { return mujoco_xr::mj_from_xr_pos(p_xr); }, "p_xr"_a,
        "XR reference-space point (metres, Y-up) -> MuJoCo world point (Z-up). Applies both the "
        "handedness rotation and the workspace translation.");

    m.def(
        "mj_from_xr_quat", [](std::array<double, 4> q_xyzw) { return mujoco_xr::mj_from_xr_quat(q_xyzw); }, "q_xyzw"_a,
        "XR orientation as xyzw (the order OpenXR and Teleop's GRIP_ORIENTATION use) -> MuJoCo world "
        "orientation as wxyz. The ONLY quaternion crossing in the app.");

    // Module ATTRIBUTES, not m.def getters, and SCREAMING_CASE. In C++ these are
    // `inline constexpr` and the casing already separates them from the
    // snake_case conversion functions above -- but a getter exports as a
    // snake_case attribute too, so `quat_mj_from_xr` and `mj_from_xr_quat` would
    // sit side by side in Python with nothing but word order telling a constant
    // apart from a transform. The case carries that here, exactly as in C++.
    // Immutable tuples, so the Python surface cannot be mutated for the process;
    // the prose lives in frames.hpp, which is where the values are defined.
    //
    // QUAT_MJ_FROM_XR: the fixed handedness convention Rz(-90) * Rx(+90), wxyz.
    // TRANS_MJ_FROM_XR: the workspace calibration (operator standoff, floor
    //   datum) in MuJoCo metres.
    m.attr("QUAT_MJ_FROM_XR") = py::tuple(py::cast(mujoco_xr::kQuatMjFromXr));
    m.attr("TRANS_MJ_FROM_XR") = py::tuple(py::cast(mujoco_xr::kTransMjFromXr));

    // ── Projection ────────────────────────────────────────────────────────

    m.def(
        "projection_from_fov",
        [](std::array<float, 4> fov_lrud, float near_z, float far_z)
        {
            const auto p = mujoco_xr::projection_from_fov(fov_lrud, near_z, far_z);
            return std::vector<float>(p.begin(), p.end());
        },
        "fov_lrud"_a, "near_z"_a, "far_z"_a,
        "Column-major 4x4 Vulkan-convention projection from (angle_left, angle_right, angle_up, angle_down) "
        "in radians. Same code path the renderer uses; exposed so the clip convention is testable without a "
        "GPU. Raises ValueError on a degenerate (all-zero) fov.");

    // ── Renderer ──────────────────────────────────────────────────────────

    py::class_<mujoco_xr::CudaImageView>(m, "CudaImageView",
                                         R"doc(
Non-owning CUDA view of one of the renderer's staging buffers.

Exposes ``__cuda_array_interface__``, which is all
``isaacteleop.viz.ProjectionLayer.submit()`` needs. Do NOT hold one past the
frame it came from, and never past ``Renderer.close()``: the memory belongs to
the renderer.
)doc")
        .def_property_readonly("__cuda_array_interface__", &mujoco_xr::CudaImageView::cuda_array_interface)
        .def_readonly("width", &mujoco_xr::CudaImageView::width)
        .def_readonly("height", &mujoco_xr::CudaImageView::height);

    py::class_<mujoco_xr::PyRenderer>(m, "Renderer",
                                      R"doc(
MuJoCo scene renderer writing into CUDA-visible colour + depth buffers.

Constructed from a live ``isaacteleop.viz.VizSession``'s raw handles -- it
BORROWS that Vulkan device and queue rather than creating its own, which is
what lets the exported memory be imported by the same CUDA context viz uses.

Per frame, in this order and on ONE thread::

    info = session.begin_frame()
    if info.should_render:
        mujoco.mj_step(model, data)          # Python owns the simulation
        renderer.update_scene(m_addr, d_addr)
        renderer.clear_markers(); renderer.add_marker(...)
        renderer.render(poses, fovs)         # poses/fovs from info.views
        layer.submit(renderer.color(0), renderer.depth(0), ...)
    session.end_frame()

``render()`` blocks until the GPU work has retired, so the buffers are safe to
submit the moment it returns.
)doc")
        .def(py::init<uintptr_t, uintptr_t, uint32_t, uint32_t, uint32_t, uint32_t, float, float, uintptr_t>(),
             "vk_physical_device"_a, "vk_device"_a, "vk_queue_family_index"_a, "width"_a, "height"_a, "view_count"_a,
             "near_z"_a, "far_z"_a, "model_address"_a,
             "All handles are plain integers: VizSession.vk_physical_device / .vk_device / "
             ".vk_queue_family_index, and mujoco.MjModel._address.")
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
            "clear_markers", [](mujoco_xr::PyRenderer& self) { self.get().clear_markers(); },
            "Drop the decor geoms appended since the last update_scene.")
        .def(
            "add_marker",
            [](mujoco_xr::PyRenderer& self, std::array<double, 3> pos_mj, std::array<double, 4> quat_mj_wxyz,
               std::array<double, 3> half_extent, std::array<float, 4> rgba)
            { self.get().add_marker(pos_mj, quat_mj_wxyz, half_extent, rgba); },
            "pos_mj"_a, "quat_mj_wxyz"_a, "half_extent"_a, "rgba"_a,
            "Append one box marker in MuJoCo world coordinates. Display only -- markers carry no control "
            "authority. Orientation is wxyz (MuJoCo's order), NOT the xyzw an XR pose arrives in; run it "
            "through mj_from_xr_quat first.")
        .def(
            "render",
            [](mujoco_xr::PyRenderer& self, std::vector<float> poses_xyz_qwxyz, std::vector<float> fovs_lrud)
            {
                // Releasing the GIL here removes the ONLY mechanical
                // serialisation this module had against a second Python thread
                // calling into viz on the same borrowed VkQueue. The app is
                // single-threaded by contract (scene_renderer.hpp's THREADING
                // note), and the release is what keeps a long GPU wait from
                // blocking that whole interpreter -- but the contract is now
                // the only thing holding, so do not multi-thread the frame loop
                // without adding real synchronisation around the queue.
                py::gil_scoped_release release;
                self.get().render(poses_xyz_qwxyz, fovs_lrud);
            },
            "poses_xyz_qwxyz"_a, "fovs_lrud"_a,
            "Render every view. `poses_xyz_qwxyz` is view_count*7 floats (x, y, z, qw, qx, qy, qz) and "
            "`fovs_lrud` is view_count*4 (angle_left, angle_right, angle_up, angle_down) -- flatten them "
            "from FrameInfo.views. Blocks until the GPU work retires.")
        .def(
            "projection",
            [](mujoco_xr::PyRenderer& self, int view)
            {
                const auto& p = self.get().projection(view);
                return std::vector<float>(p.begin(), p.end());
            },
            "view"_a,
            "The column-major 4x4 projection used for `view` on the last render(), so the caller can assert "
            "the clip convention per frame.")
        .def(
            "color",
            [](mujoco_xr::PyRenderer& self, int view)
            {
                const auto& t = self.get().view_target(view);
                return mujoco_xr::CudaImageView{ reinterpret_cast<uintptr_t>(t.color().cuda_ptr()), t.width(),
                                                 t.height(), /*is_depth=*/false };
            },
            // keep_alive<0, 1>: the returned CudaImageView is a bare device
            // pointer into the Renderer's exported memory. Without this, a
            // caller who writes `buf = renderer.color(0)` and drops its last
            // reference to `renderer` gets a use-after-free at submit time,
            // with no Python-level symptom pointing back here.
            py::keep_alive<0, 1>(), "view"_a,
            "RGBA8 colour for `view` as a CudaImageView. Valid until the next render().")
        .def(
            "depth",
            [](mujoco_xr::PyRenderer& self, int view)
            {
                const auto& t = self.get().view_target(view);
                return mujoco_xr::CudaImageView{ reinterpret_cast<uintptr_t>(t.depth().cuda_ptr()), t.width(),
                                                 t.height(), /*is_depth=*/true };
            },
            py::keep_alive<0, 1>(), "view"_a, // see color() above
            "D32_SFLOAT depth for `view` as a CudaImageView, standard Z: near -> 0.0, far -> 1.0. Valid until "
            "the next render().")
        .def_property_readonly("view_count", [](mujoco_xr::PyRenderer& self) { return self.get().view_count(); })
        .def_property_readonly("ngeom", [](mujoco_xr::PyRenderer& self) { return self.get().ngeom(); })
        .def_property_readonly("maxgeom", [](mujoco_xr::PyRenderer& self) { return self.get().maxgeom(); })
        .def("close", &mujoco_xr::PyRenderer::close,
             "Release the Vulkan and CUDA resources. Must happen BEFORE VizSession.destroy(), since the device "
             "is borrowed from it.");
}
