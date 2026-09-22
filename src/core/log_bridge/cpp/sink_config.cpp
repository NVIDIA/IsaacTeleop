// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include <spdlog/common.h>
#include <spdlog/pattern_formatter.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cstdlib>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

namespace isaacteleop::detail
{
namespace
{

// Same shape as the Python side's LINE_FORMAT (logging_config/_core.py). %* is
// PythonLevelFormatter below; spdlog's own %l is lowercase and %L a single
// letter, so neither renders the level the way Python's handlers do.
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%*] [%n] [pid:%P] %v";

// The stdlib names Python's LINE_FORMAT renders, plus TRACE
// (logging.addLevelName(TRACE, "TRACE") in logging_config/_core.py). Needed so
// a record this process formats itself reads like one that reached a file
// through Python -- the case a standalone plugin executable has to carry alone.
std::string_view python_level_name(spdlog::level::level_enum level)
{
    switch (level)
    {
    case spdlog::level::trace:
        return "TRACE";
    case spdlog::level::debug:
        return "DEBUG";
    case spdlog::level::info:
        return "INFO";
    case spdlog::level::warn:
        return "WARNING";
    case spdlog::level::err:
        return "ERROR";
    case spdlog::level::critical:
        return "CRITICAL";
    default:
        return "INFO";
    }
}

// Right-padded to 5 and never truncated, matching Python's own "%(levelname)-5s".
class PythonLevelFormatter : public spdlog::custom_flag_formatter
{
public:
    void format(const spdlog::details::log_msg& msg, const std::tm&, spdlog::memory_buf_t& dest) override
    {
        const std::string_view name = python_level_name(msg.level);
        dest.append(name.data(), name.data() + name.size());
        for (std::size_t pad = name.size(); pad < 5; ++pad)
        {
            dest.push_back(' ');
        }
    }

    std::unique_ptr<custom_flag_formatter> clone() const override
    {
        return std::make_unique<PythonLevelFormatter>();
    }
};

// A fresh formatter per sink: sink::set_formatter() takes a unique_ptr, so
// every sink needs its own instance built from the same recipe.
std::unique_ptr<spdlog::pattern_formatter> make_formatter()
{
    auto formatter = std::make_unique<spdlog::pattern_formatter>();
    formatter->add_flag<PythonLevelFormatter>('*').set_pattern(kPattern);
    return formatter;
}

// Mirrors isaacteleop.logging_config's names and integer thresholds.
// spdlog::level::from_str() is deliberately not used: it answers level::off for
// anything it does not recognise, so a typo would mute a standalone plugin
// entirely instead of falling back to info. spdlog's own "warn"/"err"
// spellings are absent for the same reason the Python half has no entry for
// them -- one operator value must not mean two different thresholds.
spdlog::level::level_enum console_level()
{
    const char* raw = std::getenv("ISAACTELEOP_LOG_LEVEL");
    if (raw == nullptr)
    {
        return spdlog::level::info;
    }

    // Trimmed before anything looks at it, as the Python half's
    // env_console_level() does: a systemd `Environment=` line, a sourced .env
    // file and a here-doc all hand this leading or trailing whitespace.
    std::string_view text(raw);
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front())))
    {
        text.remove_prefix(1);
    }
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back())))
    {
        text.remove_suffix(1);
    }

    std::string name(text);
    std::transform(
        name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    static constexpr std::pair<std::string_view, spdlog::level::level_enum> kNames[] = {
        { "trace", spdlog::level::trace },  { "debug", spdlog::level::debug }, { "info", spdlog::level::info },
        { "warning", spdlog::level::warn }, { "error", spdlog::level::err },   { "critical", spdlog::level::critical },
    };
    for (const auto& [candidate, level] : kNames)
    {
        if (name == candidate)
        {
            return level;
        }
    }

    std::string_view digits(name);
    if (!digits.empty() && (digits.front() == '+' || digits.front() == '-'))
    {
        digits.remove_prefix(1);
    }
    if (digits.empty() || !std::all_of(digits.begin(), digits.end(), [](char c) { return c >= '0' && c <= '9'; }))
    {
        return spdlog::level::info;
    }

    std::string_view numeric_name(name);
    if (!numeric_name.empty() && numeric_name.front() == '+')
    {
        numeric_name.remove_prefix(1);
    }
    long long numeric = 0;
    const auto [end, ec] = std::from_chars(numeric_name.data(), numeric_name.data() + numeric_name.size(), numeric);
    if (ec == std::errc::result_out_of_range && end == numeric_name.data() + numeric_name.size())
    {
        return !numeric_name.empty() && numeric_name.front() == '-' ? spdlog::level::trace : spdlog::level::off;
    }
    if (ec == std::errc{} && end == numeric_name.data() + numeric_name.size())
    {
        if (numeric <= 5)
        {
            return spdlog::level::trace;
        }
        if (numeric <= 10)
        {
            return spdlog::level::debug;
        }
        if (numeric <= 20)
        {
            return spdlog::level::info;
        }
        if (numeric <= 30)
        {
            return spdlog::level::warn;
        }
        if (numeric <= 40)
        {
            return spdlog::level::err;
        }
        if (numeric <= 50)
        {
            return spdlog::level::critical;
        }
        return spdlog::level::off;
    }
    return spdlog::level::info;
}

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        // Nothing here may throw: this builds the sinks every logger is created
        // with, and Logger::get() -- which every diagnostic call site in the tree
        // treats as infallible -- is a function-local static, so an initializer
        // that throws stays uninitialised and throws again on the next call.
        // stderr, like the Python half's console handler: on stdout a standalone
        // tool's own product and its diagnostics share one descriptor, so
        // `tool > data.txt` both swallows the diagnostics and corrupts the data.
        auto console = std::make_shared<spdlog::sinks::stderr_color_sink_mt>();
        console->set_level(console_level());
        console->set_formatter(make_formatter());
        return std::vector<spdlog::sink_ptr>{ console };
    }();
    return sinks;
}

} // namespace isaacteleop::detail
