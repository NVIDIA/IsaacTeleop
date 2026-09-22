// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/details/log_msg.h>
#include <spdlog/details/null_mutex.h>
#include <spdlog/sinks/base_sink.h>

namespace isaacteleop
{

// Formats nothing itself -- forwards the already-substituted message and level
// to Python's logging.getLogger(name).log(level, message), so Python's handlers
// apply the single, unified timestamp/format.
//
// Holds no Python reference between records, and must not acquire one: this sink
// outlives Py_Finalize() (it is owned by statics), so a pybind11::object member
// would decref into a torn-down interpreter.
//
// null_mutex, not std::mutex, is a correctness requirement. base_sink<Mutex>::log()
// holds mutex_ across sink_it_(), and every logger in the process shares this one
// instance, so a real mutex here would be held while gil_scoped_acquire blocks --
// deadlocking a C++ thread that logs (holds sink mutex, wants GIL) against a Python
// thread in a binding that logs (holds GIL, wants sink mutex). Nothing here needs
// the mutual exclusion: the GIL serializes the body and Python's logging is
// itself thread-safe.
class PythonBridgeSink : public spdlog::sinks::base_sink<spdlog::details::null_mutex>
{
protected:
    void sink_it_(const spdlog::details::log_msg& msg) override;
    void flush_() override;
};

// Swaps every logger's sinks (existing and future) to a shared PythonBridgeSink.
// Exposed to Python as install_python_sink(); first call only.
//
// Scope is this shared object, not the process: log_bridge_core is a static
// library and each extension module carries its own bridge pointer and spdlog
// registry. See log_bridge/AGENTS.md for how those modules' records still reach
// Python.
void install_python_sink();

} // namespace isaacteleop
