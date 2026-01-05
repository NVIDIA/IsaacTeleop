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
    py::class_<core::ITracker, std::shared_ptr<core::ITracker>>(m, "ITracker")
        .def("is_initialized", &core::ITracker::is_initialized)
        .def("get_name", &core::ITracker::get_name);

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

    // Hand enum
    py::enum_<core::Hand>(m, "Hand").value("Left", core::Hand::Left).value("Right", core::Hand::Right).export_values();

    // ControllerInput enum - with arithmetic to make it iterable
    // ControllerInputState structure
    py::class_<core::ControllerInputState>(m, "ControllerInputState")
        .def(py::init<>())
        .def_readonly("primary_click", &core::ControllerInputState::primary_click)
        .def_readonly("secondary_click", &core::ControllerInputState::secondary_click)
        .def_readonly("thumbstick_click", &core::ControllerInputState::thumbstick_click)
        .def_readonly("thumbstick_x", &core::ControllerInputState::thumbstick_x)
        .def_readonly("thumbstick_y", &core::ControllerInputState::thumbstick_y)
        .def_readonly("squeeze_value", &core::ControllerInputState::squeeze_value)
        .def_readonly("trigger_value", &core::ControllerInputState::trigger_value);

    // ControllerPose structure
    py::class_<core::ControllerPose>(m, "ControllerPose")
        .def(py::init<>())
        .def_property_readonly("position", [](const core::ControllerPose& self)
                               { return py::array_t<float>({ 3 }, { sizeof(float) }, self.position); })
        .def_property_readonly("orientation", [](const core::ControllerPose& self)
                               { return py::array_t<float>({ 4 }, { sizeof(float) }, self.orientation); })
        .def_readonly("is_valid", &core::ControllerPose::is_valid);

    // ControllerSnapshot structure
    py::class_<core::ControllerSnapshot>(m, "ControllerSnapshot")
        .def(py::init<>())
        .def_readonly("grip_pose", &core::ControllerSnapshot::grip_pose)
        .def_readonly("aim_pose", &core::ControllerSnapshot::aim_pose)
        .def_readonly("inputs", &core::ControllerSnapshot::inputs)
        .def_readonly("is_active", &core::ControllerSnapshot::is_active)
        .def_readonly("timestamp", &core::ControllerSnapshot::timestamp);

    // ControllerTracker class
    py::class_<core::ControllerTracker, core::ITracker, std::shared_ptr<core::ControllerTracker>>(m, "ControllerTracker")
        .def(py::init<>())
        .def("get_snapshot", &core::ControllerTracker::get_snapshot, py::arg("hand"),
             py::return_value_policy::reference_internal,
             "Get current controller snapshot for specified hand (includes poses and inputs)");

    // DeviceIOSession class (bound via wrapper for context management)
    py::class_<PyDeviceIOSession>(m, "DeviceIOSession")
        .def("update", &PyDeviceIOSession::update, "Update session and all trackers")
        .def("__enter__", &PyDeviceIOSession::enter)
        .def("__exit__", &PyDeviceIOSession::exit)
        .def_static("get_required_extensions", &core::DeviceIOSession::get_required_extensions, py::arg("trackers"),
                    "Get list of OpenXR extensions required by a list of trackers")
        .def_static(
            "run",
            [](const std::vector<std::shared_ptr<core::ITracker>>& trackers, const core::OpenXRSessionHandles& handles,
               const std::string& mcap_recording_path)
            {
                // run() throws exceptions on failure, which pybind11 converts to Python exceptions
                auto session = core::DeviceIOSession::run(trackers, handles, mcap_recording_path);
                // Wrap unique_ptr in PyDeviceIOSession, then unique_ptr for Python ownership
                return std::make_unique<PyDeviceIOSession>(std::move(session));
            },
            py::arg("trackers"), py::arg("handles"), py::arg("mcap_recording_path") = "",
            "Create and initialize a session with trackers (returns context-managed session, throws on failure). "
            "If mcap_recording_path is provided, MCAP recording will be started automatically.");

    // Module constants - XR_HAND_JOINT_COUNT_EXT
    m.attr("NUM_JOINTS") = 26;

    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}
