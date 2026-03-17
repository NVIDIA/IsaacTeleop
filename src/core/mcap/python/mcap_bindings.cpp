// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio_base/tracker.hpp>
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

    void record(const core::ITrackerSession& session)
    {
        if (!recorder_)
        {
            throw std::runtime_error("Recorder has been closed");
        }
        recorder_->record(session);
    }

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

    py::module_::import("isaacteleop.deviceio_trackers._deviceio_trackers");
    py::module_::import("isaacteleop.deviceio_session._deviceio_session");

    py::class_<PyMcapRecorder>(m, "McapRecorder")
        .def_static(
            "create",
            [](const std::string& filename, const std::vector<core::McapRecorder::TrackerChannelPair>& trackers)
            { return std::make_unique<PyMcapRecorder>(core::McapRecorder::create(filename, trackers)); },
            py::arg("filename"), py::arg("trackers"),
            "Create a recorder for an MCAP file with the specified trackers. "
            "Returns a context-managed recorder.")
        .def(
            "record", [](PyMcapRecorder& self, const core::ITrackerSession& session) { self.record(session); },
            py::arg("session"), "Record the current state of all registered trackers")
        .def("__enter__", &PyMcapRecorder::enter)
        .def("__exit__", &PyMcapRecorder::exit);
}
