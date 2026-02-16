// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "plugin_manager/plugin_manager.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
using namespace core;

PYBIND11_MODULE(_plugin_manager, m)
{
    m.doc() = "Isaac Teleop Plugin Manager bindings";

    // Register custom exception
    py::register_exception<PluginCrashException>(m, "PluginCrashException");

    py::class_<Plugin, std::unique_ptr<Plugin>>(m, "Plugin")
        .def("stop", &Plugin::stop, "Explicitly stop the plugin (throws PluginCrashException if crashed)")
        .def("check_health", &Plugin::check_health, "Check if plugin has crashed (throws PluginCrashException if crashed)")
        .def("__enter__", [](Plugin* self) { return self; })
        .def("__exit__", [](Plugin* self, py::object, py::object, py::object) { self->stop(); });

    py::class_<PluginManager>(m, "PluginManager")
        .def(py::init<const std::vector<std::string>&>(), py::arg("search_paths"),
             "Create a PluginManager and discover plugins in the given search paths")
        .def("get_plugin_names", &PluginManager::get_plugin_names, "Get list of discovered plugin names")
        .def("query_devices", &PluginManager::query_devices, py::arg("plugin_name"),
             "Query available devices from a plugin")
        .def("start", &PluginManager::start, py::arg("plugin_name"), py::arg("plugin_root_id"),
             py::arg("plugin_args") = std::vector<std::string>{}, "Start a plugin and return a RAII handle.");
}
