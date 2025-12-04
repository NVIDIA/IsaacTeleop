// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <openxr/openxr.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <xrio/handtracker.hpp>
#include <xrio/headtracker.hpp>
#include <xrio/xrio_session.hpp>

namespace py = pybind11;

// Wrapper class to enforce RAII in Python by holding the shared_ptr exclusively
class PyXrioSession
{
public:
    PyXrioSession(std::shared_ptr<core::XrioSession> impl) : impl_(impl)
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

    PyXrioSession& enter()
    {
        return *this;
    }

    // Reset shared_ptr on exit to enforce destruction
    void exit(py::object, py::object, py::object)
    {
        close();
    }

private:
    std::shared_ptr<core::XrioSession> impl_;
};

PYBIND11_MODULE(_xrio, m)
{
    m.doc() = "TeleopCore XRIO - Extended Reality I/O Module";

    // JointPose structure
    py::class_<core::JointPose>(m, "JointPose")
        .def(py::init<>())
        .def_property_readonly("position", [](const core::JointPose& self)
                               { return py::array_t<float>({ 3 }, { sizeof(float) }, self.position); })
        .def_property_readonly("orientation", [](const core::JointPose& self)
                               { return py::array_t<float>({ 4 }, { sizeof(float) }, self.orientation); })
        .def_readonly("radius", &core::JointPose::radius)
        .def_readonly("is_valid", &core::JointPose::is_valid);

    // HandData structure
    py::class_<core::HandData>(m, "HandData")
        .def(py::init<>())
        .def(
            "get_joint",
            [](const core::HandData& self, size_t index) -> const core::JointPose&
            {
                if (index >= core::HandData::NUM_JOINTS)
                {
                    throw py::index_error("Joint index out of range");
                }
                return self.joints[index];
            },
            py::return_value_policy::reference_internal)
        .def_readonly("is_active", &core::HandData::is_active)
        .def_readonly("timestamp", &core::HandData::timestamp)
        .def_property_readonly("num_joints", [](const core::HandData&) { return core::HandData::NUM_JOINTS; });

    // HeadPose structure
    py::class_<core::HeadPose>(m, "HeadPose")
        .def(py::init<>())
        .def_property_readonly("position", [](const core::HeadPose& self)
                               { return py::array_t<float>({ 3 }, { sizeof(float) }, self.position); })
        .def_property_readonly("orientation", [](const core::HeadPose& self)
                               { return py::array_t<float>({ 4 }, { sizeof(float) }, self.position); })
        .def_readonly("is_valid", &core::HeadPose::is_valid)
        .def_readonly("timestamp", &core::HeadPose::timestamp);

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

    // XrioSession class (bound via wrapper)
    py::class_<PyXrioSession>(m, "XrioSession")
        .def("update", &PyXrioSession::update, "Update session and all trackers")
        .def("__enter__", &PyXrioSession::enter)
        .def("__exit__", &PyXrioSession::exit);

    // XrioSessionBuilder class
    py::class_<core::XrioSessionBuilder>(m, "XrioSessionBuilder")
        .def(py::init<>(), "Create a builder")
        .def("add_tracker", &core::XrioSessionBuilder::add_tracker, py::arg("tracker"), "Add a tracker to the builder")
        .def("get_required_extensions", &core::XrioSessionBuilder::get_required_extensions,
             "Get list of OpenXR extensions required by all trackers")
        .def(
            "build",
            [](core::XrioSessionBuilder& self, const core::OpenXRSessionHandles& handles)
            {
                auto session = self.build(handles);
                if (!session)
                    return std::unique_ptr<PyXrioSession>(nullptr);
                // Wrap shared_ptr in PyXrioSession, then unique_ptr for Python ownership
                return std::make_unique<PyXrioSession>(session);
            },
            py::arg("handles"), "Build a xrio session with OpenXR session handles");

    // Module constants
    m.attr("NUM_JOINTS") = core::HandData::NUM_JOINTS;

    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}
