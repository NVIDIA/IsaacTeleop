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
#include "mesh_buffers.hpp"
#include "render_target.hpp"
#include "scene_renderer.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace mujoco_xr
{
namespace
{

namespace py = pybind11;

// A view onto one of the renderer's CUDA-visible staging buffers, shaped for
// viz's `cuda_array_to_viz_buffer` helper, which wants:
//   kRGBA8 -> typestr "|u1", shape (H, W, 4)
//   kD32F  -> typestr "<f4", shape (H, W)
// and accepts strides=None for tightly-packed rows, which ours always are.
//
// Non-owning: the pointer belongs to the SceneRenderer, so these are produced
// fresh per frame rather than cached on the Python side.
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

    m.def(
        "mesh_triangles",
        [](uintptr_t model_address, int meshid)
        {
            const mjModel* model = reinterpret_cast<const mjModel*>(model_address);
            mujoco_xr::MeshBuffers mb;
            mujoco_xr::build_mesh_buffers(model, &mb);
            if (meshid < 0 || meshid >= static_cast<int>(mb.meshes.size()))
            {
                throw std::out_of_range("mujoco_xr: meshid out of range");
            }
            const mujoco_xr::MeshRange& r = mb.meshes[static_cast<size_t>(meshid)];
            std::vector<float> pos, normal;
            pos.reserve(r.index_count * 3);
            normal.reserve(r.index_count * 3);
            const size_t base = static_cast<size_t>(r.base_vertex);
            for (uint32_t i = 0; i < r.index_count; ++i)
            {
                const mujoco_xr::Vertex& v = mb.verts[base + mb.indices[r.first_index + i]];
                pos.insert(pos.end(), { v.pos[0], v.pos[1], v.pos[2] });
                normal.insert(normal.end(), { v.normal[0], v.normal[1], v.normal[2] });
            }
            return std::make_pair(pos, normal);
        },
        "model_address"_a, "meshid"_a,
        "The vertices the RENDERER draws for one mesh: (positions, normals), both 3 floats per corner in "
        "draw order, so a test can check the normals against the geometry they came from. mjModel's own "
        "normals are not these -- see cpp/mesh_buffers.hpp.");

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

    // Attributes rather than m.def getters, and SCREAMING_CASE: a getter would
    // export as a snake_case attribute, putting `quat_mj_from_xr` beside
    // `mj_from_xr_quat` with only word order telling a constant from a
    // transform. Immutable tuples; the values and their prose live in
    // frames.hpp.
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
        .def_property_readonly("__cuda_array_interface__", &mujoco_xr::CudaImageView::cuda_array_interface);

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
            "render",
            [](mujoco_xr::PyRenderer& self, std::vector<float> poses_xyz_qwxyz, std::vector<float> fovs_lrud)
            {
                // Releasing the GIL keeps a long GPU wait from blocking the
                // interpreter, but it also drops the only mechanical
                // serialisation against a second thread calling into viz on the
                // same borrowed VkQueue. The single-threaded contract in
                // scene_renderer.hpp is now the only thing holding: do not
                // multi-thread the frame loop without real queue
                // synchronisation.
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
