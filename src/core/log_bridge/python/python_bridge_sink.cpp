// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "python_bridge_sink.hpp"

#include <log_bridge/logger.hpp>
#include <pybind11/pybind11.h>

#include <mutex>
#include <string>

namespace isaacteleop
{

void PythonBridgeSink::sink_it_(const spdlog::details::log_msg& msg)
{
    pybind11::gil_scoped_acquire gil;
    auto get_logger = pybind11::module_::import("logging").attr("getLogger");
    auto py_logger = get_logger(std::string(msg.logger_name.begin(), msg.logger_name.end()));
    py_logger.attr("log")(detail::to_python_level(msg.level), std::string(msg.payload.begin(), msg.payload.end()));
}

void PythonBridgeSink::flush_()
{
    // Python's own handlers own flushing.
}

void install_python_sink()
{
    // Once per process, and the guard is load-bearing rather than tidiness.
    // set_bridge_sink() re-points every registered logger by assigning
    // logger->sinks(), and spdlog does not synchronize that vector against the
    // logging path -- a logger emitting a record on another thread is reading
    // the same vector. The bootstrap call from isaacteleop/__init__.py runs on
    // the importing thread before anything here has started logging, so it is
    // safe; a second call from a running application would not be, and this
    // function is public API. A repeat call has nothing to do anyway: it would
    // install an equivalent sink over the one already in place.
    static std::once_flag installed;
    std::call_once(installed, [] { detail::set_bridge_sink(std::make_shared<PythonBridgeSink>()); });
}

} // namespace isaacteleop
