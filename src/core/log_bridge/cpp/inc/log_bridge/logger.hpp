// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <spdlog/logger.h>

#include <memory>
#include <string>

// Deliberately isaaccapture::, not core:: -- Logger is used uniformly by both
// core:: and core::plugins:: code, and its logger names mirror the Python
// side's isaaccapture.<module>.<ClassName> dotted convention -- a sibling of
// core, not nested in it.
namespace isaaccapture
{

class Logger
{
public:
    // Returns the (memoized) logger for `name`, e.g.
    // "isaaccapture.plugins.manus.ManusTracker". The same name always returns
    // the same instance, matching spdlog::get()/spdlog::create()'s own
    // registry. Sinks either forward over the session socket or fall back to
    // this process's console and rotating file.
    static std::shared_ptr<spdlog::logger> get(const std::string& name);
};

// False when ISAACCAPTURE_LOGGING is "off" (read as Python reads it): loggers then
// write every level to stderr, with no log file and no forwarding.
bool logging_enabled();

namespace detail
{

// isaaccapture.logging_config's level constants (Python's stdlib levels, plus
// TRACE = 5), used by SocketForwardSink's wire format.
int to_python_level(spdlog::level::level_enum level);

} // namespace detail

} // namespace isaaccapture
