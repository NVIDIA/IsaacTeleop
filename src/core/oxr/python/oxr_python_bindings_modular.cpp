#include <oxr/oxr_manager.hpp>
#include <oxr/oxr_handtracker.hpp>
#include <oxr/oxr_headtracker.hpp>

#include <openxr/openxr.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

namespace py = pybind11;

PYBIND11_MODULE(oxr_tracking, m) {
    m.doc() = "OpenXR Modular Tracking Python Bindings";

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

    // OpenXRManager class
    py::class_<oxr::OpenXRManager>(m, "OpenXRManager")
        .def(py::init<>())
        .def("add_tracker", &oxr::OpenXRManager::add_tracker,
             "Add a tracker to the manager")
        .def("get_required_extensions", &oxr::OpenXRManager::get_required_extensions,
             "Get list of OpenXR extensions required by all added trackers")
        .def("initialize", 
             [](oxr::OpenXRManager& self, const std::string& app_name,
                py::object external_instance, py::object external_session, py::object external_space) {
                 // Check if external handles provided (as integers)
                 XrInstance inst = XR_NULL_HANDLE;
                 XrSession sess = XR_NULL_HANDLE;
                 XrSpace space = XR_NULL_HANDLE;
                 
                 if (!external_instance.is_none() && !external_session.is_none() && !external_space.is_none()) {
                     // Convert Python integers back to OpenXR handles
                     inst = reinterpret_cast<XrInstance>(external_instance.cast<size_t>());
                     sess = reinterpret_cast<XrSession>(external_session.cast<size_t>());
                     space = reinterpret_cast<XrSpace>(external_space.cast<size_t>());
                 }
                 
                 return self.initialize(app_name, inst, sess, space);
             },
             py::arg("app_name") = "OpenXR",
             py::arg("external_instance") = py::none(),
             py::arg("external_session") = py::none(),
             py::arg("external_space") = py::none(),
             "Initialize OpenXR session. Pass instance/session/space to reuse external session.")
        .def("shutdown", &oxr::OpenXRManager::shutdown,
             "Shutdown and cleanup")
        .def("is_initialized", &oxr::OpenXRManager::is_initialized)
        .def("update", &oxr::OpenXRManager::update,
             "Update all trackers")
        .def("get_instance", [](const oxr::OpenXRManager& self) {
             return reinterpret_cast<size_t>(self.get_instance());
         }, "Get OpenXR instance handle as integer (for C++ sharing)")
        .def("get_session", [](const oxr::OpenXRManager& self) {
             return reinterpret_cast<size_t>(self.get_session());
         }, "Get OpenXR session handle as integer (for C++ sharing)")
        .def("get_space", [](const oxr::OpenXRManager& self) {
             return reinterpret_cast<size_t>(self.get_space());
         }, "Get OpenXR space handle as integer (for C++ sharing)")
        .def("__enter__", [](oxr::OpenXRManager& self) -> oxr::OpenXRManager& {
            return self;
        })
        .def("__exit__", [](oxr::OpenXRManager& self, py::object, py::object, py::object) {
            self.shutdown();
        });

    // Module constants
    m.attr("NUM_JOINTS") = oxr::HandData::NUM_JOINTS;
    
    // Joint indices
    m.attr("JOINT_PALM") = static_cast<int>(XR_HAND_JOINT_PALM_EXT);
    m.attr("JOINT_WRIST") = static_cast<int>(XR_HAND_JOINT_WRIST_EXT);
    m.attr("JOINT_THUMB_TIP") = static_cast<int>(XR_HAND_JOINT_THUMB_TIP_EXT);
    m.attr("JOINT_INDEX_TIP") = static_cast<int>(XR_HAND_JOINT_INDEX_TIP_EXT);
}

