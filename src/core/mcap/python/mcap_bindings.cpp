// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Prevent Windows.h from defining min/max macros that conflict with std::min/max
#if defined(_WIN32) || defined(_WIN64)
#    define NOMINMAX
#endif

#include <deviceio/deviceio_session.hpp>
#include <deviceio/tracker.hpp>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <mcap_recorder.hpp>

namespace py = pybind11;

// Wrapper class to manage McapRecorder lifetime with Python context manager
class PyMcapRecorder
{
public:
    PyMcapRecorder(std::unique_ptr<core::McapRecorder> recorder) : recorder_(std::move(recorder))
    {
    }

    void stop_recording()
    {
        if (recorder_)
        {
            recorder_->stop_recording();
        }
    }

    bool is_recording() const
    {
        return recorder_ && recorder_->is_recording();
    }

    bool record(core::DeviceIOSession& session)
    {
        if (!recorder_)
        {
            throw std::runtime_error("Recorder has been closed");
        }
        return recorder_->record(session);
    }

    // Context manager support
    PyMcapRecorder& enter()
    {
        return *this;
    }

    void exit(py::object, py::object, py::object)
    {
        stop_recording();
    }

private:
    std::unique_ptr<core::McapRecorder> recorder_;
};

PYBIND11_MODULE(_mcap, m)
{
    m.doc() = "TeleopCore MCAP - MCAP Recording Module";

    // Import deviceio module to get core::DeviceIOSession type registered
    // This ensures cross-module type compatibility
    py::module_::import("teleopcore.deviceio._deviceio");

    // McapRecorder class
    py::class_<PyMcapRecorder>(m, "McapRecorder")
        .def_static(
            "start_recording",
            [](const std::string& filename, const std::vector<core::McapRecorder::TrackerChannelPair>& trackers)
            {
                auto recorder = core::McapRecorder::start_recording(filename, trackers);
                if (!recorder)
                {
                    throw std::runtime_error("Failed to start recording to " + filename);
                }
                return std::make_unique<PyMcapRecorder>(std::move(recorder));
            },
            py::arg("filename"), py::arg("trackers"),
            "Start recording to an MCAP file with the specified trackers. "
            "Returns a context-managed recorder.")
        .def("stop_recording", &PyMcapRecorder::stop_recording, "Stop recording and close the MCAP file")
        .def("is_recording", &PyMcapRecorder::is_recording, "Check if recording is currently active")
        .def(
            "record",
            [](PyMcapRecorder& self, py::object session)
            {
                // Get the native DeviceIOSession reference from the Python wrapper
                // The _native() method is exposed by deviceio module and returns core::DeviceIOSession&
                py::object native_obj = session.attr("_native")();
                auto& native_session = native_obj.cast<core::DeviceIOSession&>();
                return self.record(native_session);
            },
            py::arg("session"), "Record the current state of all registered trackers")
        .def("__enter__", &PyMcapRecorder::enter)
        .def("__exit__", &PyMcapRecorder::exit);
}
