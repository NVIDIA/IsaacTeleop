// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/log_bridge/logger.hpp"

#include "sink_config.hpp"

#include <spdlog/spdlog.h>

#include <mutex>

namespace isaaccapture
{
namespace detail
{
namespace
{

// Serialize each logger's check-create-register sequence.
std::mutex& creation_mutex()
{
    static std::mutex m;
    return m;
}

} // namespace

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

std::shared_ptr<spdlog::logger> Logger::get(const std::string& name)
{
    std::lock_guard<std::mutex> lock(detail::creation_mutex());

    if (auto existing = spdlog::get(name))
    {
        return existing;
    }

    const auto& sinks = detail::local_sinks();
    auto logger = std::make_shared<spdlog::logger>(name, sinks.begin(), sinks.end());
    logger->set_level(spdlog::level::trace);
    spdlog::register_logger(logger);
    return logger;
}

} // namespace isaaccapture
