#include <xrio/teleop_session.hpp>
#include <xrio/handtracker.hpp>
#include <xrio/headtracker.hpp>

#include <openxr/openxr.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

namespace py = pybind11;

PYBIND11_MODULE(_xrio, m) {
    m.doc() = "TeleopCore XRIO - Extended Reality I/O Module";

    // JointPose structure
    py::class_<oxr::JointPose>(m, "JointPose")
        .def(py::init<>())
        .def_property_readonly("position", 
            [](const oxr::JointPose& self) {
                return py::array_t<float>({3}, {sizeof(float)}, self.position);
            })
        .def_property_readonly("orientation", 
            [](const oxr::JointPose& self) {
                return py::array_t<float>({4}, {sizeof(float)}, self.orientation);
            })
        .def_readonly("radius", &oxr::JointPose::radius)
        .def_readonly("is_valid", &oxr::JointPose::is_valid);

    // HandData structure
    py::class_<oxr::HandData>(m, "HandData")
        .def(py::init<>())
        .def("get_joint", 
            [](const oxr::HandData& self, size_t index) -> const oxr::JointPose& {
                if (index >= oxr::HandData::NUM_JOINTS) {
                    throw py::index_error("Joint index out of range");
                }
                return self.joints[index];
            }, py::return_value_policy::reference_internal)
        .def_readonly("is_active", &oxr::HandData::is_active)
        .def_readonly("timestamp", &oxr::HandData::timestamp)
        .def_property_readonly("num_joints", [](const oxr::HandData&) {
            return oxr::HandData::NUM_JOINTS;
        });

    // HeadPose structure
    py::class_<oxr::HeadPose>(m, "HeadPose")
        .def(py::init<>())
        .def_property_readonly("position", 
            [](const oxr::HeadPose& self) {
                return py::array_t<float>({3}, {sizeof(float)}, self.position);
            })
        .def_property_readonly("orientation", 
            [](const oxr::HeadPose& self) {
                return py::array_t<float>({4}, {sizeof(float)}, self.position);
            })
        .def_readonly("is_valid", &oxr::HeadPose::is_valid)
        .def_readonly("timestamp", &oxr::HeadPose::timestamp);

    // ITracker interface (base class)
    py::class_<oxr::ITracker, std::shared_ptr<oxr::ITracker>>(m, "ITracker")
        .def("is_initialized", &oxr::ITracker::is_initialized)
        .def("get_name", &oxr::ITracker::get_name);

    // HandTracker class
    py::class_<oxr::HandTracker, oxr::ITracker, std::shared_ptr<oxr::HandTracker>>(m, "HandTracker")
        .def(py::init<>())
        .def("get_left_hand", &oxr::HandTracker::get_left_hand,
             py::return_value_policy::reference_internal)
        .def("get_right_hand", &oxr::HandTracker::get_right_hand,
             py::return_value_policy::reference_internal)
        .def_static("get_joint_name", &oxr::HandTracker::get_joint_name);

    // HeadTracker class
    py::class_<oxr::HeadTracker, oxr::ITracker, std::shared_ptr<oxr::HeadTracker>>(m, "HeadTracker")
        .def(py::init<>())
        .def("get_head", &oxr::HeadTracker::get_head,
             py::return_value_policy::reference_internal);

    // OpenXRSessionHandles is imported from teleopcore.oxr, not defined here
    // We need to use the type from the other module for builder.build()
    
    // TeleopSessionBuilder class (Builder pattern)
    py::class_<oxr::TeleopSessionBuilder>(m, "TeleopSessionBuilder")
        .def(py::init<>(), "Create a builder")
        .def("add_tracker", &oxr::TeleopSessionBuilder::add_tracker,
             py::arg("tracker"),
             "Add a tracker to the builder")
        .def("get_required_extensions", &oxr::TeleopSessionBuilder::get_required_extensions,
             "Get list of OpenXR extensions required by all trackers")
        .def("build",
             [](oxr::TeleopSessionBuilder& self, const oxr::OpenXRSessionHandles& handles) {
                 return self.build(handles);
             },
             py::arg("handles"),
             "Build a teleop session with OpenXR session handles");

    // TeleopSession class
    py::class_<oxr::TeleopSession, std::shared_ptr<oxr::TeleopSession>>(m, "TeleopSession")
        .def("update", &oxr::TeleopSession::update,
             "Update session and all trackers")
        .def("__enter__", [](oxr::TeleopSession& self) -> oxr::TeleopSession& {
            return self;
        })
        .def("__exit__", [](oxr::TeleopSession& self, py::object, py::object, py::object) {
            // RAII cleanup handled automatically when object is destroyed
        });

    // Module constants
    m.attr("NUM_JOINTS") = oxr::HandData::NUM_JOINTS;
    
    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}

