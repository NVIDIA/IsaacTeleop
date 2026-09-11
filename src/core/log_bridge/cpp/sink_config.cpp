// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include "socket_sink.hpp"

#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <string>

#ifndef _WIN32
#    include <unistd.h>
#else
#    include <process.h>
#endif

namespace isaacteleop::detail
{
namespace
{

constexpr std::size_t kFileMaxBytes = 10 * 1024 * 1024; // 10 MiB
constexpr std::size_t kFileBackupCount = 5;
// [timestamp] [LEVEL ] [logger.name] [pid:N] message -- same shape as the
// Python side's LINE_FORMAT (isaacteleop/logging_config.py).
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%-7l] [%n] [pid:%P] %v";

int current_pid()
{
#ifndef _WIN32
    return static_cast<int>(::getpid());
#else
    return static_cast<int>(::_getpid());
#endif
}

// Local time, filename-safe (no ':' or ' '): YYYYMMDD-HHMMSS.
std::string current_timestamp()
{
    const std::time_t now = std::time(nullptr);
    std::tm tm_buf{};
#ifndef _WIN32
    ::localtime_r(&now, &tm_buf);
#else
    ::localtime_s(&tm_buf, &now);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y%m%d-%H%M%S", &tm_buf);
    return std::string(buf);
}

std::filesystem::path log_dir()
{
    if (const char* override_dir = std::getenv("ISAACTELEOP_LOG_DIR"); override_dir != nullptr)
    {
        return std::filesystem::path(override_dir);
    }
    return "/tmp/isaacteleop/logs";
}

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
        // forwarder) so its own logging_config.py receiver becomes the one place that
        // formats, filters, and persists every process's records -- the session's
        // single log file. Standalone/manual runs with nothing to forward to (no
        // ISAACTELEOP_LOG_SOCKET) fall back to this process's own console+file sinks
        // below, unchanged from before this existed.
        if (auto socket_path = forwarding_socket_path(); !socket_path.empty())
        {
            auto forward = std::make_shared<SocketForwardSink>(std::move(socket_path));
            forward->set_level(spdlog::level::trace); // the receiver's own logger does the filtering
            return std::vector<spdlog::sink_ptr>{ forward };
        }

        auto dir = log_dir();
        std::filesystem::create_directories(dir);
        // One file per process: concurrent processes rotating a shared file
        // can corrupt it, so each process gets its own (mirrors the Python
        // side's <timestamp>.isaacteleop.<pid>.log default). The leading
        // timestamp makes the run's start time the first thing the name says,
        // keeps a run's files adjacent whatever produced them, and guards
        // against a reused pid colliding with an older run's file; the pid
        // still guards against two processes starting in the same second.
        auto filename = dir / (current_timestamp() + ".isaacteleop." + std::to_string(current_pid()) + ".log");

        auto console = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        console->set_level(console_level());
        console->set_pattern(kPattern);

        auto file =
            std::make_shared<spdlog::sinks::rotating_file_sink_mt>(filename.string(), kFileMaxBytes, kFileBackupCount);
        file->set_level(spdlog::level::debug); // always captures everything, not user-configurable
        file->set_pattern(kPattern);

        return std::vector<spdlog::sink_ptr>{ console, file };
    }();
    return sinks;
}

} // namespace isaacteleop::detail
