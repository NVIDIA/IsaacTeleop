// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Emits exactly one isaacteleop::Logger record, then exits.
//
//     log_bridge_emit_record <logger-name> <level> <message>
//
// A separate executable rather than a helper function, because local_sinks()
// (src/core/log_bridge/cpp/sink_config.cpp) decides between the forwarding sink
// and the console+file sinks once per process, inside a function-local static.
// One binary can therefore only ever be in one of those states, so each routing
// case needs a process of its own.
//
// Both halves of the routing suite drive this same binary: test_routing.cpp
// beside it runs it for the two local states, and
// tests/python/core/logging_config/test_logging_config.py runs it against a real
// receiver -- the only place the C++ sender and the Python receiver are ever
// checked against each other.
//
// The environment is read by the library, not by this file:
// ISAACTELEOP_LOG_SOCKET selects forwarding, ISAACTELEOP_LOG_DIR holds the local
// log file, ISAACTELEOP_LOG_LEVEL is the console sink's threshold.

#include <log_bridge/logger.hpp>
#include <spdlog/common.h>

#include <cstdio>
#include <cstring>

namespace
{

//! Spelled out rather than spdlog::level::from_str(), which answers level::off
//! for anything it does not recognise: a typo would emit nothing at all, and a
//! caller would read that silence as a routing failure instead of a bad
//! argument. Same reasoning as sink_config.cpp's console_level().
bool parse_level(const char* name, spdlog::level::level_enum& out)
{
    const struct
    {
        const char* name;
        spdlog::level::level_enum level;
    } known[] = {
        { "trace", spdlog::level::trace },  { "debug", spdlog::level::debug }, { "info", spdlog::level::info },
        { "warning", spdlog::level::warn }, { "error", spdlog::level::err },   { "critical", spdlog::level::critical },
    };
    for (const auto& entry : known)
    {
        if (std::strcmp(entry.name, name) == 0)
        {
            out = entry.level;
            return true;
        }
    }
    return false;
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 4)
    {
        std::fprintf(stderr, "usage: %s <logger-name> <level> <message>\n", argv[0]);
        return 2;
    }

    spdlog::level::level_enum level{};
    if (!parse_level(argv[2], level))
    {
        std::fprintf(stderr, "unknown level: %s\n", argv[2]);
        return 2;
    }

    // ThirdParty, so the level argument is honoured verbatim: an Application
    // logger defaults to debug and would drop a trace record before any sink --
    // including the one under test -- ever saw it.
    auto logger = isaacteleop::Logger::get(argv[1], isaacteleop::LoggerKind::ThirdParty);
    logger->log(level, "{}", argv[3]);
    logger->flush();
    return 0;
}
