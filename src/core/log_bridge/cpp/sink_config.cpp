// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include <spdlog/details/fmt_helper.h>
#include <spdlog/pattern_formatter.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <algorithm>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <memory>
#include <optional>
#include <regex>
#include <string>
#include <string_view>
#include <unordered_map>

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
// As kPattern, but the name goes through the %* custom flag so it can carry an
// emphasis colour. The file keeps %n: escape sequences in a log file are noise.
constexpr const char* kConsolePattern = "[%Y-%m-%d %H:%M:%S.%e] [%-7l] [%*] [pid:%P] %v";
constexpr const char* kAnsiReset = "\033[0m";

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

// ISAACTELEOP_LOG_COLORS, written by logging_config.set_logger_colors(), as
// "logger.name=<sgr escape>" entries joined by ','. The Python side validates every
// value against a strict SGR pattern, which is what makes ',' and '=' unambiguous
// separators: an accepted escape can contain neither.
const std::unordered_map<std::string, std::string>& logger_colors()
{
    static const auto colors = []
    {
        std::unordered_map<std::string, std::string> parsed;
        const char* raw = std::getenv("ISAACTELEOP_LOG_COLORS");
        std::string_view rest(raw != nullptr ? raw : "");
        while (!rest.empty())
        {
            const auto entry = rest.substr(0, rest.find(','));
            rest.remove_prefix(std::min(entry.size() + 1, rest.size()));
            if (const auto separator = entry.find('='); separator != std::string_view::npos)
            {
                parsed.emplace(entry.substr(0, separator), entry.substr(separator + 1));
            }
        }
        return parsed;
    }();
    return colors;
}

// ISAACTELEOP_LOG_FILTER / ISAACTELEOP_LOG_FILTER_TARGET, written by
// logging_config.set_console_filter(). Mirrors the Python KeywordFilter: a search, not
// a full match, against the logger name, the message, or either.
class ConsoleFilter
{
public:
    ConsoleFilter()
    {
        const char* pattern = std::getenv("ISAACTELEOP_LOG_FILTER");
        if (pattern == nullptr)
        {
            return;
        }
        m_regex.emplace(pattern);
        const char* target = std::getenv("ISAACTELEOP_LOG_FILTER_TARGET");
        const std::string_view resolved(target != nullptr ? target : "both");
        m_match_logger_name = resolved != "content";
        m_match_content = resolved != "logger_name";
    }

    bool accepts(const spdlog::details::log_msg& msg) const
    {
        if (!m_regex.has_value())
        {
            return true;
        }
        return (m_match_logger_name && search(msg.logger_name)) || (m_match_content && search(msg.payload));
    }

private:
    bool search(spdlog::string_view_t text) const
    {
        return std::regex_search(text.begin(), text.end(), *m_regex);
    }

    std::optional<std::regex> m_regex;
    bool m_match_logger_name = true;
    bool m_match_content = true;
};

const ConsoleFilter& console_filter()
{
    static const ConsoleFilter filter;
    return filter;
}

// A plugin is fork+exec'd (core/plugin_manager) and inherits fd 1, so its console
// output reaches the operator's terminal without ever passing through the parent's
// Python handler. Filtering here is what makes one configured console view hold for
// both sides. The file sink is deliberately left unfiltered.
class FilteredConsoleSink final : public spdlog::sinks::stdout_color_sink_mt
{
public:
    void log(const spdlog::details::log_msg& msg) override
    {
        if (console_filter().accepts(msg))
        {
            Base::log(msg);
        }
    }

private:
    // The base is an alias template instantiation, so its name is not injected.
    using Base = spdlog::sinks::stdout_color_sink_mt;
};

// The %* flag: the logger name, wrapped in its registered emphasis colour.
class ColoredLoggerName final : public spdlog::custom_flag_formatter
{
public:
    void format(const spdlog::details::log_msg& msg, const std::tm& /*tm_time*/, spdlog::memory_buf_t& dest) override
    {
        const auto& colors = logger_colors();
        const auto match = colors.find(std::string(msg.logger_name.begin(), msg.logger_name.end()));
        if (match != colors.end())
        {
            spdlog::details::fmt_helper::append_string_view(match->second, dest);
            spdlog::details::fmt_helper::append_string_view(msg.logger_name, dest);
            spdlog::details::fmt_helper::append_string_view(kAnsiReset, dest);
            return;
        }
        spdlog::details::fmt_helper::append_string_view(msg.logger_name, dest);
    }

    std::unique_ptr<spdlog::custom_flag_formatter> clone() const override
    {
        return spdlog::details::make_unique<ColoredLoggerName>();
    }
};

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        auto dir = log_dir();
        std::filesystem::create_directories(dir);
        // One file per process: concurrent processes rotating a shared file
        // can corrupt it, so each process gets its own (mirrors the Python
        // side's isaacteleop.<timestamp>.<pid>.log default). The timestamp
        // makes the file's creation time greppable/sortable from its name and
        // guards against a reused pid colliding with an older run's file; the
        // pid still guards against two processes starting in the same second.
        auto filename = dir / ("isaacteleop." + current_timestamp() + "." + std::to_string(current_pid()) + ".log");

        auto console = std::make_shared<FilteredConsoleSink>();
        console->set_level(console_level());
        // add_flag before set_pattern: the pattern is parsed on assignment, so a %*
        // in it resolves only once the handler for that flag is registered.
        auto formatter = spdlog::details::make_unique<spdlog::pattern_formatter>();
        formatter->add_flag<ColoredLoggerName>('*').set_pattern(kConsolePattern);
        console->set_formatter(std::move(formatter));

        auto file =
            std::make_shared<spdlog::sinks::rotating_file_sink_mt>(filename.string(), kFileMaxBytes, kFileBackupCount);
        file->set_level(spdlog::level::debug); // always captures everything, not user-configurable
        file->set_pattern(kPattern);

        return std::vector<spdlog::sink_ptr>{ console, file };
    }();
    return sinks;
}

} // namespace isaacteleop::detail
