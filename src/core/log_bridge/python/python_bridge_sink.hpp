// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pybind11/pybind11.h>
#include <spdlog/details/log_msg.h>
#include <spdlog/details/null_mutex.h>
#include <spdlog/sinks/base_sink.h>

namespace isaacteleop
{

// Formats nothing itself -- forwards the already-substituted message and
// level to Python's logging.getLogger(name).log(level, message), so
// Python's handlers apply the single, unified timestamp/format.
//
// null_mutex, not std::mutex: base_sink::log() locks before calling sink_it_,
// which acquires the GIL -- a std::mutex here means one lock order is
// mutex-then-GIL, while any pybind entry point that logs without releasing the
// GIL is GIL-then-mutex, and the two deadlock. One instance is shared by every
// logger in the process (set_bridge_sink), so that pair is reachable from any
// two threads. sink_it_ does nothing but call Python, so the GIL it must take
// anyway is the only mutual exclusion this sink needs.
class PythonBridgeSink : public spdlog::sinks::base_sink<spdlog::details::null_mutex>
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
