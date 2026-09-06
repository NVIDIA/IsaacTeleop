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

std::mutex& bridge_mutex()
{
    static std::mutex m;
    return m;
}

// Guards Logger::get()'s check-then-create-then-register sequence: without
// this, two threads racing to create the same new name could both pass the
// spdlog::get() check and then both call register_logger(), breaking the
// "same name always returns the same instance" guarantee.
std::mutex& creation_mutex()
{
    static std::mutex m;
    return m;
}

std::shared_ptr<spdlog::sinks::sink>& bridge_sink_storage()
{
    static std::shared_ptr<spdlog::sinks::sink> sink;
    return sink;
}

} // namespace

std::shared_ptr<spdlog::sinks::sink> bridge_sink()
{
    std::lock_guard<std::mutex> lock(bridge_mutex());
    return bridge_sink_storage();
}

void set_bridge_sink(std::shared_ptr<spdlog::sinks::sink> sink)
{
    {
        std::lock_guard<std::mutex> lock(bridge_mutex());
        bridge_sink_storage() = sink;
    }
    spdlog::apply_all([&sink](const std::shared_ptr<spdlog::logger>& logger) { logger->sinks() = { sink }; });
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
