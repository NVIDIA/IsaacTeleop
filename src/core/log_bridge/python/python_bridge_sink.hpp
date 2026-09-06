// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <spdlog/details/log_msg.h>
#include <spdlog/sinks/base_sink.h>

#include <mutex>

namespace isaacteleop
{

// Formats nothing itself -- forwards the already-substituted message and
// level to Python's logging.getLogger(name).log(level, message), so
// Python's handlers apply the single, unified timestamp/format.
class PythonBridgeSink : public spdlog::sinks::base_sink<std::mutex>
{
public:
    PythonBridgeSink();

protected:
    void sink_it_(const spdlog::details::log_msg& msg) override;
    void flush_() override;

private:
    pybind11::object get_logger_fn_; // cached `logging.getLogger`, resolved under GIL in ctor
};

// Installs the bridge: swaps every logger's sinks (existing and future) to
// a shared PythonBridgeSink. Exposed to Python as install_python_sink().
void install_python_sink();

} // namespace isaacteleop
