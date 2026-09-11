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
    // once install_python_sink() has run, the Python bridge -- see
    // detail::set_bridge_sink() below.
    static std::shared_ptr<spdlog::logger> get(const std::string& name, LoggerKind kind = LoggerKind::Application);
};

// Internal seam between log_bridge_core (this library; no pybind11/Python.h)
// and log_bridge_py (src/core/log_bridge/python/), which is the only other
// consumer of these two functions. Exported (not a private header) because
// log_bridge_py is a separate CMake target within the same log_bridge
// module -- not because this is meant for general use.
namespace detail
{

// Null until install_python_sink() has run in this process.
std::shared_ptr<spdlog::sinks::sink> bridge_sink();

// Called only from log_bridge_py's install_python_sink(). Every logger
// created by Logger::get() from this point on uses `sink` exclusively
// (replacing, not adding to, the local console+file sinks -- a bridged
// record must not also be independently formatted into a local file, since
// Python's handlers already apply the single, unified timestamp/format).
// Also swaps the sinks of every logger already created before this call, to
// cover static-init-order edge cases where C++ logs before Python installs
// the bridge.
void set_bridge_sink(std::shared_ptr<spdlog::sinks::sink> sink);

// isaacteleop.logging_config's level constants (Python's stdlib levels, plus the
// module's own TRACE = 5). Shared by every sink that hands a record to Python's
// logging module -- directly in-process (log_bridge_py's PythonBridgeSink) or
// serialized across a socket to another process's Python logger (SocketForwardSink,
// this library) -- so both speak the exact same numbering as
// isaacteleop/logging_config.py's _LEVEL_NAMES.
int to_python_level(spdlog::level::level_enum level);

} // namespace detail

} // namespace isaacteleop
