// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/log_bridge/logger.hpp"

#include "sink_config.hpp"

#include <spdlog/spdlog.h>

#include <mutex>

namespace isaacteleop
{
namespace detail
{
namespace
{

// Guards Logger::get()'s check-then-create-then-register sequence -- without
// it two threads racing on the same new name could both pass the spdlog::get()
// check and both register -- and, held across set_bridge_sink(), the bridge
// pointer below. A logger racing that call therefore either registers before
// its apply_all sweep (and gets swapped by it) or is created afterwards (and
// picks up the new sink at creation), never in the gap between.
std::mutex& creation_mutex()
{
    static std::mutex m;
    return m;
}

// Null until install_python_sink() has run in this process. Only ever read or
// written under creation_mutex().
std::shared_ptr<spdlog::sinks::sink>& bridge_sink()
{
    static std::shared_ptr<spdlog::sinks::sink> sink;
    return sink;
}

} // namespace

void set_bridge_sink(std::shared_ptr<spdlog::sinks::sink> sink)
{
    std::lock_guard<std::mutex> lock(creation_mutex());
    bridge_sink() = sink;
    spdlog::apply_all([&sink](const std::shared_ptr<spdlog::logger>& logger) { logger->sinks() = { sink }; });
}

// No call site in this tree logs at critical today; spdlog::critical still maps onto
// logging.CRITICAL, which is 50, not ERROR's 40.
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
        return 50;
    default:
        return 20;
    }
}

} // namespace detail

std::shared_ptr<spdlog::logger> Logger::get(const std::string& name, LoggerKind kind)
{
    std::lock_guard<std::mutex> lock(detail::creation_mutex());

    if (auto existing = spdlog::get(name))
    {
        return existing;
    }

    std::shared_ptr<spdlog::logger> logger;
    if (auto sink = detail::bridge_sink())
    {
        logger = std::make_shared<spdlog::logger>(name, sink);
    }
    else
    {
        const auto& sinks = detail::local_sinks();
        logger = std::make_shared<spdlog::logger>(name, sinks.begin(), sinks.end());
    }
    logger->set_level(kind == LoggerKind::ThirdParty ? spdlog::level::trace : spdlog::level::debug);
    spdlog::register_logger(logger);
    return logger;
}

} // namespace isaacteleop
