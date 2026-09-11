// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include <spdlog/sinks/stdout_color_sinks.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <system_error>

#ifndef _WIN32
#    include <unistd.h>
#endif

namespace isaacteleop::detail
{
namespace
{

// [timestamp] [LEVEL ] [logger.name] [pid:N] message -- same shape as the
// Python side's LINE_FORMAT (isaacteleop/logging_config).
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%-7l] [%n] [pid:%P] %v";

// Must resolve to the same place as isaacteleop.logging_config's log_dir(),
// including the uid: a single shared /tmp/isaacteleop is created by whichever
// user reaches it first and is then unwritable for everyone else on the machine.
std::filesystem::path log_dir()
{
    if (const char* override_dir = std::getenv("ISAACTELEOP_LOG_DIR"); override_dir != nullptr)
    {
        return std::filesystem::path(override_dir);
    }
#ifndef _WIN32
    return "/tmp/isaacteleop-" + std::to_string(static_cast<unsigned>(::getuid())) + "/logs";
#else
    return "/tmp/isaacteleop/logs";
#endif
}

// Mirrors isaacteleop.logging_config's _LEVEL_NAMES, which lowercases before
// looking up and falls back to info. spdlog::level::from_str() is deliberately
// not used here: it answers level::off for anything it does not recognise, so
// the "DEBUG" a user naturally writes -- or any typo -- would silently mute the
// console of every standalone plugin instead of falling back to the default.
spdlog::level::level_enum console_level()
{
    const char* level_str = std::getenv("ISAACTELEOP_LOG_LEVEL");
    if (level_str == nullptr)
    {
        return spdlog::level::info;
    }

    std::string name(level_str);
    std::transform(
        name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    if (name == "trace")
    {
        return spdlog::level::trace;
    }
    if (name == "debug")
    {
        return spdlog::level::debug;
    }
    if (name == "info")
    {
        return spdlog::level::info;
    }
    if (name == "warning" || name == "warn")
    {
        return spdlog::level::warn;
    }
    if (name == "error" || name == "err")
    {
        return spdlog::level::err;
    }
    return spdlog::level::info;
}

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        auto dir = log_dir();
        const bool dir_created = std::filesystem::create_directories(dir);
#ifndef _WIN32
        if (dir_created)
        {
            // Matches the Python side: owner-only, so the records and the raw fd
            // captures beside them are not readable by other users of the machine.
            // Only when this call created it -- an operator-chosen ISAACTELEOP_LOG_DIR
            // keeps the permissions the operator gave it.
            std::error_code perms_ec;
            std::filesystem::permissions(
                dir, std::filesystem::perms::owner_all, std::filesystem::perm_options::replace, perms_ec);
        }
#else
        (void)dir_created;
#endif

        auto console = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        console->set_level(console_level());
        console->set_pattern(kPattern);

        return std::vector<spdlog::sink_ptr>{ console };
    }();
    return sinks;
}

} // namespace isaacteleop::detail
