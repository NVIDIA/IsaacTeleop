// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include "socket_sink.hpp"

#include <spdlog/sinks/stdout_color_sinks.h>

#include <cstdlib>

namespace isaacteleop::detail
{
namespace
{

// [timestamp] [LEVEL ] [logger.name] [pid:N] message -- same shape as the
// Python side's LINE_FORMAT (isaacteleop/logging_config).
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%-7l] [%n] [pid:%P] %v";

spdlog::level::level_enum console_level()
{
    const char* level_str = std::getenv("ISAACTELEOP_LOG_LEVEL");
    return level_str != nullptr ? spdlog::level::from_str(level_str) : spdlog::level::info;
}

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        // Set by the process that spawned us (the session leader, or an intermediate
        // forwarder) so its own logging_config receiver becomes the one place that
        // formats and filters every process's records. Standalone/manual runs with
        // nothing to forward to (no ISAACTELEOP_LOG_SOCKET) fall back to this
        // process's own console sink below, unchanged from before this existed.
        if (auto socket_path = forwarding_socket_path(); !socket_path.empty())
        {
            auto forward = std::make_shared<SocketForwardSink>(std::move(socket_path));
            forward->set_level(spdlog::level::trace); // the receiver's own logger does the filtering
            return std::vector<spdlog::sink_ptr>{ forward };
        }

        auto console = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        console->set_level(console_level());
        console->set_pattern(kPattern);

        return std::vector<spdlog::sink_ptr>{ console };
    }();
    return sinks;
}

} // namespace isaacteleop::detail
