// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "python_bridge_sink.hpp"

#include <log_bridge/logger.hpp>

#include <string>

namespace isaacteleop
{
namespace
{

// isaacteleop.logging_config's level constants (Python's stdlib levels, plus
// the module's own TRACE = 5). critical never fires from C++ (unused, kept
// out of the level set for parity with the Python side) but is mapped for
// completeness in case spdlog::critical is ever called directly.
int to_python_level(spdlog::level::level_enum level)
{
    switch (level)
    {
    case spdlog::level::trace:
        return 5;
    case spdlog::level::debug:
        return 10;
    case spdlog::level::info:
        return 20;
    case spdlog::level::warn:
        return 30;
    case spdlog::level::err:
        return 40;
    case spdlog::level::critical:
        return 40;
    default:
        return 20;
    }
}

} // namespace

PythonBridgeSink::PythonBridgeSink()
{
    // Only ever constructed from install_python_sink(), itself only callable
    // from Python -- so the GIL is already held here.
    get_logger_fn_ = pybind11::module_::import("logging").attr("getLogger");
}

void PythonBridgeSink::sink_it_(const spdlog::details::log_msg& msg)
{
    pybind11::gil_scoped_acquire gil;
    auto py_logger = get_logger_fn_(std::string(msg.logger_name.begin(), msg.logger_name.end()));
    py_logger.attr("log")(to_python_level(msg.level), std::string(msg.payload.begin(), msg.payload.end()));
}

void PythonBridgeSink::flush_()
{
    // Python's own handlers own flushing.
}

void install_python_sink()
{
    detail::set_bridge_sink(std::make_shared<PythonBridgeSink>());
}

} // namespace isaacteleop
