// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Prevent Windows.h from defining min/max macros that conflict with std::min/max
#if defined(_WIN32) || defined(_WIN64)
#    define NOMINMAX
#endif

#include <deviceio/controllertracker.hpp>
#include <deviceio/deviceio_session.hpp>
#include <deviceio/handtracker.hpp>
#include <deviceio/headtracker.hpp>
#include <openxr/openxr.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

// Wrapper class to enforce RAII in Python by holding the unique_ptr exclusively
class PyDeviceIOSession
{
public:
    PyDeviceIOSession(std::unique_ptr<core::DeviceIOSession> impl) : impl_(std::move(impl))
    {
    }

    bool update()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return impl_->update();
    }

    void close()
    {
        impl_.reset(); // Destroys the underlying C++ object!
    }

    PyDeviceIOSession& enter()
    {
        return *this;
    }

    // Reset unique_ptr on exit to enforce destruction
    void exit(py::object, py::object, py::object)
    {
        close();
    }

private:
    std::unique_ptr<core::DeviceIOSession> impl_;
};

PYBIND11_MODULE(_deviceio, m)
{
    m.doc() = "TeleopCore DeviceIO - Device I/O Module";

    // ITracker interface (base class)
    py::class_<core::ITracker, std::shared_ptr<core::ITracker>>(m, "ITracker").def("get_name", &core::ITracker::get_name);

    // HandTracker class
    py::class_<core::HandTracker, core::ITracker, std::shared_ptr<core::HandTracker>>(m, "HandTracker")
        .def(py::init<>())
        .def("get_left_hand", &core::HandTracker::get_left_hand, py::return_value_policy::reference_internal)
        .def("get_right_hand", &core::HandTracker::get_right_hand, py::return_value_policy::reference_internal)
        .def_static("get_joint_name", &core::HandTracker::get_joint_name);

    // HeadTracker class
    py::class_<core::HeadTracker, core::ITracker, std::shared_ptr<core::HeadTracker>>(m, "HeadTracker")
        .def(py::init<>())
        .def("get_head", &core::HeadTracker::get_head, py::return_value_policy::reference_internal);

    // ControllerTracker class
    py::class_<core::ControllerTracker, core::ITracker, std::shared_ptr<core::ControllerTracker>>(m, "ControllerTracker")
        .def(py::init<>())
        .def("get_controller_data", &core::ControllerTracker::get_controller_data,
             py::return_value_policy::reference_internal,
             "Get complete controller data for both left and right controllers");

    // DeviceIOSession class (bound via wrapper for context management)
    py::class_<PyDeviceIOSession>(m, "DeviceIOSession")
        .def("update", &PyDeviceIOSession::update, "Update session and all trackers")
        .def("__enter__", &PyDeviceIOSession::enter)
        .def("__exit__", &PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Get list of OpenXR extensions required by a list of trackers")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles)
            {
                // run() throws exceptions on failure, which pybind11 converts to Python exceptions
                auto session = core::DeviceIOSession::run(trackers, handles);
                // Wrap unique_ptr in PyDeviceIOSession, then unique_ptr for Python ownership
                return std::make_unique<PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"),
            "Create and initialize a session with trackers (returns context-managed session, throws on failure)");

    // Module constants - XR_HAND_JOINT_COUNT_EXT
    m.attr("NUM_JOINTS") = 26;

    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}
