// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/details/log_msg.h>
#include <spdlog/details/null_mutex.h>
#include <spdlog/sinks/base_sink.h>

namespace isaacteleop
{

// Formats nothing itself -- forwards the already-substituted message and
// level to Python's logging.getLogger(name).log(level, message), so
// Python's handlers apply the single, unified timestamp/format.
//
// Holds no Python reference between records, and must not acquire one:
// install_python_sink() hands this sink to bridge_sink_storage() and to every logger in
// spdlog's registry, both of which have static storage duration, so it is destroyed
// after Py_Finalize() has already run -- a pybind11::object member would decref into a
// torn-down interpreter there. Re-resolving logging.getLogger per record costs two dict
// lookups on a path that already takes the GIL and builds two Python strings.
//
// null_mutex, not std::mutex, and that is a correctness requirement rather than an
// optimization. base_sink<Mutex>::log() holds mutex_ across sink_it_(), so a std::mutex
// here would be held while gil_scoped_acquire blocks -- and install_python_sink() gives
// *every* logger in the process this one shared instance, so that mutex is global to all
// C++ logging. A background C++ thread logging (holds the sink mutex, waits for the GIL)
// against a Python thread calling a binding that logs (holds the GIL, waits for the sink
// mutex) is then a deadlock. Nothing below needs the sink's own mutual exclusion anyway:
// the GIL serializes the body, and Python's logging module is itself thread-safe.
class PythonBridgeSink : public spdlog::sinks::base_sink<spdlog::details::null_mutex>
{
protected:
    void sink_it_(const spdlog::details::log_msg& msg) override;
    void flush_() override;
};

// Installs the bridge: swaps every logger's sinks (existing and future) to
// a shared PythonBridgeSink. Exposed to Python as install_python_sink().
void install_python_sink();

} // namespace isaacteleop
