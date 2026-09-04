// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// pybind11 entry point for `isaacteleop.viz.robot._robot_twin`.
//
// Nothing typed crosses this boundary in either direction. viz::Pose3D / Fov are
// registered in `_viz` and not castable here (this module links no viz target), so poses
// and fovs cross as flat float arrays. No mjModel or mjData crosses at all: this module
// allocates them, and Python reads them through the zero-copy numpy views below. That is
// what makes the private MuJoCo an implementation detail -- there is no second copy whose
// field layout would have to agree.

#include "frames.hpp"
#include "gl_context.hpp"
#include "glcamera.hpp"
#include "mj_api.hpp"
#include "mj_guard.hpp"
#include "scene.hpp"
#include "scene_renderer.hpp"

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace robot_twin
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
    PyRenderer(Scene& scene, uint32_t width, uint32_t height, uint32_t view_count, float near_z, float far_z)
    {
        SceneRenderer::Config cfg;
        cfg.width = width;
        cfg.height = height;
        cfg.view_count = view_count;
        cfg.near_z = near_z;
        cfg.far_z = far_z;
        renderer_ = std::make_unique<SceneRenderer>(cfg, scene);
    }

    SceneRenderer& get()
    {
        if (!renderer_)
        {
            throw std::runtime_error("robot_twin: renderer has been closed");
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

// A numpy view over memory the Scene owns. `owner` is the Python Scene object, kept
// alive by the array, so a caller holding `scene.qpos` cannot outlive the mjData under
// it. Writable, and deliberately: publishing a pose IS writing one of these.
template <typename T>
py::array_t<T> field(const py::object& owner, T* data, std::vector<py::ssize_t> shape)
{
    return py::array_t<T>(std::move(shape), data, owner);
}

CudaImageView image_view(SceneRenderer& r, int view, bool is_depth)
{
    if (view < 0 || static_cast<uint32_t>(view) >= r.view_count())
    {
        throw std::out_of_range("robot_twin: view index out of range");
    }
    const Readback& rb = r.readback();
    const auto index = static_cast<uint32_t>(view);
    void* ptr = is_depth ? rb.depth_ptr(index) : rb.color_ptr(index);
    return CudaImageView{ reinterpret_cast<uintptr_t>(ptr), rb.width(), rb.height(), is_depth };
}

} // namespace
} // namespace robot_twin

PYBIND11_MODULE(_robot_twin, m)
{
    namespace py = pybind11;
    using namespace pybind11::literals;

    // Before anything else: every mj* this module calls is a pointer resolved here, and
    // module init is the only path into the extension. mj_api.cpp says why it is not a link.
    robot_twin::mujoco::load();
    robot_twin::install_mujoco_handlers();

    m.doc() = "MuJoCo's OpenGL renderer, read back into CUDA for Isaac Teleop's Televiz ProjectionLayer.";

    m.def(
        "mujoco_version", []() { return std::string(robot_twin::mujoco::mj_versionString()); },
        "The MuJoCo this extension loaded. Unrelated to any `mujoco` wheel the process also has: this copy "
        "ships under a private name and is reached through dlsym, so the two cannot see each other. Report it "
        "wherever a scene fails to compile -- a scene authored against a newer MuJoCo says nothing about "
        "which version rejected it.");

    // ── Frames ────────────────────────────────────────────────────────────
    // Exposed rather than reimplemented, so frames.hpp stays the one definition.

    m.def(
        "mj_from_xr_pos", [](std::array<double, 3> p_xr) { return robot_twin::mj_from_xr_pos(p_xr); }, "p_xr"_a,
        "XR reference-space point (metres, Y-up) -> MuJoCo world point (Z-up). Applies both the handedness "
        "rotation and the workspace translation.");

    m.def(
        "mj_from_xr_quat", [](std::array<double, 4> q_xyzw) { return robot_twin::mj_from_xr_quat(q_xyzw); }, "q_xyzw"_a,
        "XR orientation as xyzw (the order OpenXR and Teleop's GRIP_ORIENTATION use) -> MuJoCo world "
        "orientation as wxyz. The ONLY quaternion crossing in the app.");

    // SCREAMING_CASE attributes, not getters: a snake_case getter would put
    // `quat_mj_from_xr` beside `mj_from_xr_quat`, with only word order telling a
    // constant from a transform.
    m.attr("QUAT_MJ_FROM_XR") = py::tuple(py::cast(robot_twin::kQuatMjFromXr));
    m.attr("TRANS_MJ_FROM_XR") = py::tuple(py::cast(robot_twin::kTransMjFromXr));

    // ── Projection ────────────────────────────────────────────────────────

    m.def(
        "frustum_from_fov",
        [](std::array<float, 4> fov_lrud, float near_z, float far_z)
        {
            const robot_twin::Frustum f = robot_twin::frustum_from_fov(fov_lrud, near_z, far_z);
            return std::vector<float>{ f.center, f.half_width, f.bottom, f.top, f.near_z, f.far_z };
        },
        "fov_lrud"_a, "near_z"_a, "far_z"_a,
        "The mjvGLCamera frustum fields for one asymmetric fov (angle_left, angle_right, angle_up, angle_down) "
        "in radians, as (center, half_width, bottom, top, near, far). Same code path the renderer uses; exposed "
        "so the convention is testable without a GPU. Raises ValueError on a degenerate fov or a bad near/far.");

    m.def(
        "submitted_depth",
        [](float distance, float near_z, float far_z) { return robot_twin::submitted_depth(distance, near_z, far_z); },
        "distance"_a, "near_z"_a, "far_z"_a,
        "What a view-space distance ahead of the eye becomes in the depth buffer handed to "
        "ProjectionLayer.submit(): standard Z, near -> 0, far -> 1. MuJoCo's renderer writes the reverse; "
        "shaders/readback inverts it.");

    // ── Scene ─────────────────────────────────────────────────────────────

    py::enum_<mjtObj>(m, "ObjType", "The object kinds Scene.id / Scene.name address.")
        .value("BODY", mjOBJ_BODY)
        .value("JOINT", mjOBJ_JOINT)
        .value("GEOM", mjOBJ_GEOM)
        .value("SITE", mjOBJ_SITE)
        .value("MATERIAL", mjOBJ_MATERIAL);

    py::enum_<mjtJoint>(m, "JointType", "Which qpos layout a joint has.")
        .value("FREE", mjJNT_FREE)
        .value("BALL", mjJNT_BALL)
        .value("SLIDE", mjJNT_SLIDE)
        .value("HINGE", mjJNT_HINGE);

    py::class_<robot_twin::Scene>(m, "Scene",
                                  R"doc(
A compiled MJCF, owned by this extension.

Every array below is a zero-copy view over the mjModel / mjData this object owns, and
every one is writable: publishing a pose IS writing one. They keep the Scene alive, so a
held view cannot dangle -- but they are only meaningful on the thread that owns the
scene, and `forward()` is what makes a write visible to a read.
)doc")
        .def(py::init<const std::string&>(), "path"_a,
             "Compile an MJCF. Raises RuntimeError carrying MuJoCo's own parse error.")
        .def("forward", &robot_twin::Scene::forward,
             "Forward kinematics (mj_kinematics + mj_camlight), which is what refreshes every field the "
             "renderer reads after a write to qpos / body_* / mocap_*. No dynamics: nothing here is "
             "integrated.")
        .def("id", &robot_twin::Scene::id, "obj_type"_a, "name"_a, "The object's index, or -1 if absent.")
        .def("name", &robot_twin::Scene::name, "obj_type"_a, "index"_a,
             "The object's name, or an empty string if it has none.")
        .def(
            "disable_multisampling", [](robot_twin::Scene& self) { self.model()->vis.quality.offsamples = 0; },
            "MuJoCo resolves multisample renderbuffers only inside mjr_readPixels, which the readback path "
            "never calls, and a multisample source cannot be blitted with a y flip in one step.")
        .def_property_readonly("nq", [](robot_twin::Scene& s) { return s.model()->nq; })
        .def_property_readonly("njnt", [](robot_twin::Scene& s) { return s.model()->njnt; })
        .def_property_readonly("ngeom", [](robot_twin::Scene& s) { return s.model()->ngeom; })
#define ROBOT_TWIN_FIELD(name, source, type, ...)                                                                      \
    .def_property_readonly(#name,                                                                                      \
                           [](py::object self)                                                                         \
                           {                                                                                           \
                               auto& scene = self.cast<robot_twin::Scene&>();                                          \
                               return robot_twin::field<type>(self, scene.source()->name, { __VA_ARGS__ });            \
                           })
        // mjModel: what a scene declares, and what a publish rewrites.
        ROBOT_TWIN_FIELD(jnt_type, model, int, scene.model()->njnt)
            ROBOT_TWIN_FIELD(jnt_qposadr, model, int, scene.model()->njnt)
                ROBOT_TWIN_FIELD(body_pos, model, mjtNum, scene.model()->nbody, 3)
                    ROBOT_TWIN_FIELD(body_quat, model, mjtNum, scene.model()->nbody, 4)
                        ROBOT_TWIN_FIELD(body_mocapid, model, int, scene.model()->nbody)
                            ROBOT_TWIN_FIELD(body_rootid, model, int, scene.model()->nbody)
                                ROBOT_TWIN_FIELD(geom_bodyid, model, int, scene.model()->ngeom)
                                    ROBOT_TWIN_FIELD(geom_group, model, int, scene.model()->ngeom)
                                        ROBOT_TWIN_FIELD(geom_matid, model, int, scene.model()->ngeom)
                                            ROBOT_TWIN_FIELD(mat_rgba, model, float, scene.model()->nmat, 4)
        // mjData: the pose, and what forward() derives from it.
        ROBOT_TWIN_FIELD(qpos, data, mjtNum, scene.model()->nq)
            ROBOT_TWIN_FIELD(mocap_pos, data, mjtNum, scene.model()->nmocap, 3)
                ROBOT_TWIN_FIELD(mocap_quat, data, mjtNum, scene.model()->nmocap, 4)
                    ROBOT_TWIN_FIELD(xpos, data, mjtNum, scene.model()->nbody, 3)
                        ROBOT_TWIN_FIELD(xquat, data, mjtNum, scene.model()->nbody, 4)
                            ROBOT_TWIN_FIELD(site_xpos, data, mjtNum, scene.model()->nsite, 3)
                                ROBOT_TWIN_FIELD(site_xmat, data, mjtNum, scene.model()->nsite, 9);
#undef ROBOT_TWIN_FIELD

    // ── OpenGL context ────────────────────────────────────────────────────

    py::class_<robot_twin::GlContext>(m, "GlContext",
                                      R"doc(
A headless OpenGL context, made through EGL's device platform.

Replaces ``mujoco.GLContext``, whose only job here was this. Thread-affine: the thread
that calls ``make_current()`` is the only one that may render.
)doc")
        .def(py::init<uint32_t, uint32_t, int>(), "width"_a, "height"_a, "device_index"_a = -1,
             "`device_index` picks among the EGL devices, which on a multi-GPU machine is which GPU; -1 takes "
             "the first that yields a context. Renderer's constructor is what checks the choice against the "
             "GPU viz already picked.")
        .def("make_current", &robot_twin::GlContext::make_current)
        .def_property_readonly("device_index", &robot_twin::GlContext::device_index);

    // ── Renderer ──────────────────────────────────────────────────────────

    py::class_<robot_twin::CudaImageView>(m, "CudaImageView",
                                          R"doc(
Non-owning CUDA view of one of the renderer's pixel-pack buffers.

Exposes ``__cuda_array_interface__``, which is all
``isaacteleop.viz.ProjectionLayer.submit()`` needs. Do NOT hold one past the
frame it came from, and never past ``Renderer.close()``: the memory belongs to
the renderer and is unmapped on the next ``render()``.
)doc")
        .def_property_readonly("__cuda_array_interface__", &robot_twin::CudaImageView::cuda_array_interface);

    py::class_<robot_twin::PyRenderer>(m, "Renderer",
                                       R"doc(
MuJoCo's OpenGL renderer, read back into CUDA-visible colour + depth buffers.

An OpenGL context must be current on this thread BEFORE construction, on the
same GPU viz chose (``GlContext``, whose ``device_index`` selects the card).
The constructor checks this and raises rather than render into another card's
memory.

Per frame, in this order and on ONE thread::

    scene.qpos[...] = ...                    # pose it however the app wants
    scene.forward()
    renderer.update_scene()
    renderer.render(poses, fovs)             # poses/fovs from FrameInfo.views
    layer.submit(renderer.color(0), renderer.depth(0), ...)
)doc")
        .def(py::init<robot_twin::Scene&, uint32_t, uint32_t, uint32_t, float, float>(),
             // The Scene must outlive the Renderer, which holds a reference to it.
             py::keep_alive<1, 2>(), "scene"_a, "width"_a, "height"_a, "view_count"_a, "near_z"_a, "far_z"_a,
             "No Vulkan handles: this renderer reaches viz through CUDA alone, and finds viz's GPU as the "
             "process's current CUDA device.")
        .def(
            "update_scene", [](robot_twin::PyRenderer& self) { return self.get().update_scene(); },
            "One mjv_updateScene for the frame, over the Scene this was built on. Call after posing it and "
            "after Scene.forward(), on this thread. Returns the geom count.")
        .def(
            "render",
            [](robot_twin::PyRenderer& self, std::vector<float> poses_xyz_qwxyz, std::vector<float> fovs_lrud)
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
            "frustum", [](robot_twin::PyRenderer& self, int view) { return self.get().frustum(view); }, "view"_a,
            "The mjvGLCamera frustum used for `view` on the last render(), as (center, half_width, bottom, top, "
            "near, far), so the caller can assert the convention per frame.")
        .def(
            "color",
            [](robot_twin::PyRenderer& self, int view)
            { return robot_twin::image_view(self.get(), view, /*is_depth=*/false); },
            // keep_alive<0, 1>: the view is a bare device pointer into the
            // Renderer's buffers, so a caller who keeps `buf = renderer.color(0)`
            // and drops `renderer` would use-after-free at submit time.
            py::keep_alive<0, 1>(), "view"_a,
            "RGBA8 colour for `view` as a CudaImageView. Valid until the next render().")
        .def(
            "depth",
            [](robot_twin::PyRenderer& self, int view)
            { return robot_twin::image_view(self.get(), view, /*is_depth=*/true); },
            py::keep_alive<0, 1>(), "view"_a, // see color() above
            "float32 depth for `view` as a CudaImageView, standard Z: near -> 0.0, far -> 1.0. Valid until the "
            "next render().")
        .def_property_readonly("view_count", [](robot_twin::PyRenderer& self) { return self.get().view_count(); })
        .def_property_readonly("ngeom", [](robot_twin::PyRenderer& self) { return self.get().ngeom(); })
        .def_property_readonly("maxgeom", [](robot_twin::PyRenderer& self) { return self.get().maxgeom(); })
        .def("close", &robot_twin::PyRenderer::close,
             "Release the OpenGL and CUDA resources. Must happen while the GL context is still current, so "
             "BEFORE the GlContext is dropped.");
}
