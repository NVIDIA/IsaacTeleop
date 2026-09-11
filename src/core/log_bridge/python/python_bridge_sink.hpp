// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/details/log_msg.h>
#include <spdlog/sinks/base_sink.h>

#include <mutex>

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
class PythonBridgeSink : public spdlog::sinks::base_sink<std::mutex>
{
protected:
    void sink_it_(const spdlog::details::log_msg& msg) override;
    void flush_() override;
};

// Installs the bridge: swaps every logger's sinks (existing and future) to
// a shared PythonBridgeSink. Exposed to Python as install_python_sink().
void install_python_sink();

} // namespace isaacteleop
