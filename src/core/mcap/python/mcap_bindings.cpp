// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_py_utils/session.hpp>
#include <mcap/recorder.hpp>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

// Wrapper class to manage McapRecorder lifetime with Python context manager
class PyMcapRecorder
{
public:
    PyMcapRecorder(std::unique_ptr<core::McapRecorder> recorder) : recorder_(std::move(recorder))
    {
    }

    void record(core::DeviceIOSession& session)
    {
        if (!recorder_)
        {
            throw std::runtime_error("Recorder has been closed");
        }
        recorder_->record(session);
    }

    // Context manager support
    PyMcapRecorder& enter()
    {
        return *this;
    }

    void exit(py::object, py::object, py::object)
    {
        recorder_.reset();
    }

private:
    std::unique_ptr<core::McapRecorder> recorder_;
};

PYBIND11_MODULE(_mcap, m)
{
    m.doc() = "Isaac Teleop MCAP - MCAP Recording Module";

    // Import deviceio module to get PyDeviceIOSession type registered
    // This ensures cross-module type compatibility for pybind11
    py::module_::import("isaacteleop.deviceio._deviceio");

    // McapRecorder class
    py::class_<PyMcapRecorder>(m, "McapRecorder")
        .def_static(
            "create",
            [](const std::string& filename, const std::vector<std::shared_ptr<core::ITracker>>& trackers)
            { return std::make_unique<PyMcapRecorder>(core::McapRecorder::create(filename, trackers)); },
            py::arg("filename"), py::arg("trackers"),
            "Create a recorder for an MCAP file with the specified trackers. "
            "Returns a context-managed recorder.")
        .def(
            "record",
            [](PyMcapRecorder& self, PyDeviceIOSession& session)
            {
                // Accept PyDeviceIOSession directly and call .native() in C++
                // This ensures the wrapper stays alive and prevents dangling pointers
                self.record(session.native());
            },
            py::arg("session"), "Record the current state of all registered trackers")
        .def("__enter__", &PyMcapRecorder::enter)
        .def("__exit__", &PyMcapRecorder::exit);
}
