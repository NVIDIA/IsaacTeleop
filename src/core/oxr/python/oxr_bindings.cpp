// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(_oxr, m)
{
    m.doc() = "TeleopCore OXR - OpenXR Session Module";

    // OpenXRSessionHandles structure (for sharing)
    py::class_<core::OpenXRSessionHandles>(m, "OpenXRSessionHandles")
        .def(py::init<>())
        // Constructor from raw handle values (enables non-Kit usage and external runtime integration)
        .def(py::init(
                 [](uint64_t instance, uint64_t session, uint64_t space, uint64_t xr_get_instance_proc_addr)
                 {
                     return core::OpenXRSessionHandles(
                         reinterpret_cast<XrInstance>(instance), reinterpret_cast<XrSession>(session),
                         reinterpret_cast<XrSpace>(space),
                         reinterpret_cast<PFN_xrGetInstanceProcAddr>(xr_get_instance_proc_addr));
                 }),
             py::arg("instance"), py::arg("session"), py::arg("space"), py::arg("xr_get_instance_proc_addr"),
             "Create OpenXRSessionHandles from raw handle values (as integers)")
        .def_property_readonly(
            "instance", [](const core::OpenXRSessionHandles& self) { return reinterpret_cast<size_t>(self.instance); },
            "Get OpenXR instance handle as integer")
        .def_property_readonly(
            "session", [](const core::OpenXRSessionHandles& self) { return reinterpret_cast<size_t>(self.session); },
            "Get OpenXR session handle as integer")
        .def_property_readonly(
            "space", [](const core::OpenXRSessionHandles& self) { return reinterpret_cast<size_t>(self.space); },
            "Get OpenXR space handle as integer")
        .def_property_readonly(
            "proc_addr",
            [](const core::OpenXRSessionHandles& self) { return reinterpret_cast<size_t>(self.xrGetInstanceProcAddr); },
            "Get xrGetInstanceProcAddr function pointer as integer");

    // OpenXRSession class (for creating sessions)
    py::class_<core::OpenXRSession, std::shared_ptr<core::OpenXRSession>>(m, "OpenXRSession")
        .def_static("create", &core::OpenXRSession::Create, py::arg("app_name"),
                    py::arg("extensions") = std::vector<std::string>(),
                    "Create an OpenXR session (returns None on failure)")
        .def("get_handles", &core::OpenXRSession::get_handles, "Get session handles for sharing")
        .def("__enter__", [](core::OpenXRSession& self) -> core::OpenXRSession& { return self; })
        .def("__exit__",
             [](core::OpenXRSession& self, py::object, py::object, py::object)
             {
                 // RAII cleanup handled automatically when object is destroyed
             });
}
