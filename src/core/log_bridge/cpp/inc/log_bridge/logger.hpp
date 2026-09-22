// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/logger.h>
#include <spdlog/sinks/sink.h>

#include <memory>
#include <string>

// Deliberately isaacteleop::, not core::: Logger is used uniformly by both
// core:: and core::plugins:: code, and its logger names mirror the Python
// side's isaacteleop.<module>.<ClassName> dotted convention -- a sibling of
// core, not nested in it.
namespace isaacteleop
{

enum class LoggerKind
{
    Application, // IsaacTeleop's own code -- effective level defaults to debug
    ThirdParty, // wraps vendor/SDK output -- effective level defaults to trace
};

class Logger
{
public:
    // Returns the (memoized) logger for `name`, e.g.
    // "isaacteleop.plugins.manus.ManusTracker". The same name always returns
    // the same instance, matching spdlog::get()/spdlog::create()'s own
    // registry. Sinks are either the process-local console+file sinks, or,
    // once install_python_sink() has run, the Python bridge.
    static std::shared_ptr<spdlog::logger> get(const std::string& name, LoggerKind kind = LoggerKind::Application);
};

// Internal seam between log_bridge_core (this library; no pybind11/Python.h)
// and log_bridge_py (src/core/log_bridge/python/). Exported (not a private
// header) because log_bridge_py is a separate CMake target within the same
// log_bridge module -- not because this is meant for general use.
namespace detail
{

// Called only from log_bridge_py's install_python_sink(). Every logger, already
// created or not, then uses `sink` exclusively -- replacing, not adding to, the
// local console+file sinks, since Python's handlers already apply the single
// unified timestamp/format.
void set_bridge_sink(std::shared_ptr<spdlog::sinks::sink> sink);

// isaacteleop.logging_config's level constants (Python's stdlib levels, plus
// the module's own TRACE = 5). Shared by every sink that hands a record to
// Python's logging module -- in-process (log_bridge_py's PythonBridgeSink) or
// across a socket (SocketForwardSink) -- so both speak the same numbering as
// isaacteleop/logging_config/_core.py's _LEVEL_NAMES.
int to_python_level(spdlog::level::level_enum level);

} // namespace detail

} // namespace isaacteleop
