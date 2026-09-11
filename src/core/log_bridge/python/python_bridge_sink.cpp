// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "python_bridge_sink.hpp"

#include <log_bridge/logger.hpp>

#include <pybind11/pybind11.h>

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
    detail::set_bridge_sink(std::make_shared<PythonBridgeSink>());
}

} // namespace isaacteleop
