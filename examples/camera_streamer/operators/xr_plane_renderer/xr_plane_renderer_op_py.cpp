/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "holoscan/core/arg.hpp"
#include "holoscan/core/condition.hpp"
#include "holoscan/core/fragment.hpp"
#include "holoscan/core/operator.hpp"
#include "holoscan/core/operator_spec.hpp"
#include "holoscan/core/resource.hpp"
#include "xr_plane_renderer_op.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>
#include <string>
#include <vector>

using std::string_literals::operator""s;
using pybind11::literals::operator""_a;
namespace py = pybind11;

namespace isaac_teleop::cam_streamer
{

inline void add_positional_condition_and_resource_args(holoscan::Operator* op, const py::args& args)
{
    for (auto it = args.begin(); it != args.end(); ++it)
    {
        if (py::isinstance<holoscan::Condition>(*it))
        {
            op->add_arg(it->cast<std::shared_ptr<holoscan::Condition>>());
        }
        else if (py::isinstance<holoscan::Resource>(*it))
        {
            op->add_arg(it->cast<std::shared_ptr<holoscan::Resource>>());
        }
    }
}

class PyXrPlaneRendererOp : public XrPlaneRendererOp
{
public:
    using XrPlaneRendererOp::XrPlaneRendererOp;

    PyXrPlaneRendererOp(holoscan::Fragment* fragment,
                        const py::args& args,
                        std::shared_ptr<holoscan::XrSession> xr_session,
                        const std::vector<XrPlaneConfig>& planes,
                        bool verbose,
                        const std::string& name = "xr_plane_renderer")
        : XrPlaneRendererOp(
              holoscan::ArgList{ holoscan::Arg{ "xr_session", xr_session }, holoscan::Arg{ "verbose", verbose } })
    {
        add_positional_condition_and_resource_args(this, args);
        name_ = name;
        fragment_ = fragment;

        // Set plane configs before setup
        set_plane_configs(planes);

        spec_ = std::make_shared<holoscan::OperatorSpec>(fragment);
        setup(*spec_.get());
    }
};

PYBIND11_MODULE(xr_plane_renderer, m)
{
    m.doc() = "XrPlaneRendererOp - Render camera planes in XR";

    // Expose XrPlaneConfig struct to Python
    py::class_<XrPlaneConfig>(m, "XrPlaneConfig",
                              R"doc(
Configuration for an XR camera plane.

Parameters
----------
name : str
    Unique name for this plane (e.g., "head", "left_wrist").
distance : float
    Distance from user in meters (default: 1.0).
width : float
    Width of the plane in meters (default: 1.0).
offset_x : float
    Horizontal offset in meters, + = right (default: 0.0).
offset_y : float
    Vertical offset in meters, + = up (default: 0.0).
lock_mode : str
    Plane locking mode: "lazy", "world", or "head" (default: "lazy").
look_away_angle : float
    Angle threshold for looking away in degrees (default: 45.0).
reposition_delay : float
    Delay before repositioning in seconds (default: 0.5).
transition_duration : float
    Duration of smooth transitions in seconds (default: 0.3).
is_stereo : bool
    Whether this plane uses stereo cameras (default: False).
)doc")
        .def(py::init<>())
        .def(py::init(
                 [](const std::string& name, float distance, float width, float offset_x, float offset_y,
                    const std::string& lock_mode, float look_away_angle, float reposition_delay,
                    float transition_duration, bool is_stereo)
                 {
                     XrPlaneConfig config;
                     config.name = name;
                     config.distance = distance;
                     config.width = width;
                     config.offset_x = offset_x;
                     config.offset_y = offset_y;
                     config.lock_mode = lock_mode;
                     config.look_away_angle = look_away_angle;
                     config.reposition_delay = reposition_delay;
                     config.transition_duration = transition_duration;
                     config.is_stereo = is_stereo;
                     return config;
                 }),
             "name"_a, "distance"_a = 1.0f, "width"_a = 1.0f, "offset_x"_a = 0.0f, "offset_y"_a = 0.0f,
             "lock_mode"_a = "lazy", "look_away_angle"_a = 45.0f, "reposition_delay"_a = 0.5f,
             "transition_duration"_a = 0.3f, "is_stereo"_a = false)
        .def_readwrite("name", &XrPlaneConfig::name)
        .def_readwrite("distance", &XrPlaneConfig::distance)
        .def_readwrite("width", &XrPlaneConfig::width)
        .def_readwrite("offset_x", &XrPlaneConfig::offset_x)
        .def_readwrite("offset_y", &XrPlaneConfig::offset_y)
        .def_readwrite("lock_mode", &XrPlaneConfig::lock_mode)
        .def_readwrite("look_away_angle", &XrPlaneConfig::look_away_angle)
        .def_readwrite("reposition_delay", &XrPlaneConfig::reposition_delay)
        .def_readwrite("transition_duration", &XrPlaneConfig::transition_duration)
        .def_readwrite("is_stereo", &XrPlaneConfig::is_stereo)
        .def("__repr__",
             [](const XrPlaneConfig& c)
             {
                 return "XrPlaneConfig(name='" + c.name + "', distance=" + std::to_string(c.distance) +
                        ", width=" + std::to_string(c.width) + ", offset=(" + std::to_string(c.offset_x) + ", " +
                        std::to_string(c.offset_y) + "), stereo=" + (c.is_stereo ? "True" : "False") + ")";
             });

    // Expose XrPlaneRendererOp
    py::class_<XrPlaneRendererOp, PyXrPlaneRendererOp, holoscan::Operator, std::shared_ptr<XrPlaneRendererOp>>(
        m, "XrPlaneRendererOp",
        R"doc(
Renders camera planes in XR using a single Vulkan context.

Features:
- Single Vulkan context for all planes (no VK_ERROR_DEVICE_LOST)
- Proper depth compositing between planes (farthest rendered first)
- Independent plane positioning and locking modes

Inputs:
- xr_frame_state: Frame timing from XrBeginFrameOp
- camera_frame_0: First camera
- camera_frame_1: Second camera
- ... up to camera_frame_7

Output:
- xr_composition_layer: Single composition layer with all planes rendered

Parameters
----------
fragment : Fragment
    Parent fragment.
xr_session : XrSession
    OpenXR session.
planes : list[XrPlaneConfig]
    List of plane configurations.
verbose : bool
    Enable verbose logging (default: False).
name : str
    Operator name (default: "xr_plane_renderer").

Example
-------
>>> from xr_plane_renderer import XrPlaneRendererOp, XrPlaneConfig
>>> 
>>> op = XrPlaneRendererOp(
...     fragment,
...     xr_session=session,
...     planes=[
...         XrPlaneConfig(name="head", distance=1.5, width=1.2),
...         XrPlaneConfig(name="left_wrist", distance=0.8, width=0.4, offset_x=-1.0),
...     ],
... )
)doc")
        .def(py::init<holoscan::Fragment*, const py::args&, std::shared_ptr<holoscan::XrSession>,
                      const std::vector<XrPlaneConfig>&, bool, const std::string&>(),
             "fragment"_a, "xr_session"_a, "planes"_a, "verbose"_a = false, "name"_a = "xr_plane_renderer"s)
        .def("initialize", &XrPlaneRendererOp::initialize)
        .def("setup", &XrPlaneRendererOp::setup, "spec"_a);
}

} // namespace isaac_teleop::cam_streamer
