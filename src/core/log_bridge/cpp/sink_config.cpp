// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <cstdlib>
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

std::filesystem::path log_dir()
{
    if (const char* override_dir = std::getenv("ISAACTELEOP_LOG_DIR"); override_dir != nullptr)
    {
        return std::filesystem::path(override_dir);
    }
    const char* home =
#ifndef _WIN32
        std::getenv("HOME");
#else
        std::getenv("USERPROFILE");
#endif
    return std::filesystem::path(home != nullptr ? home : ".") / ".isaacteleop" / "logs";
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
        auto dir = log_dir();
        std::filesystem::create_directories(dir);
        // One file per process: concurrent processes rotating a shared file
        // can corrupt it, so each process gets its own (mirrors the Python
        // side's isaacteleop.<pid>.log default).
        auto filename = dir / ("isaacteleop." + std::to_string(current_pid()) + ".log");

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
