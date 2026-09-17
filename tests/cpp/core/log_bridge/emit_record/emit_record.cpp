// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <log_bridge/logger.hpp>
#include <spdlog/common.h>

#include <cstdio>
#include <cstring>

namespace
{

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

    auto logger = isaacteleop::Logger::get(argv[1], isaacteleop::LoggerKind::ThirdParty);
    logger->log(level, "{}", argv[3]);
    logger->flush();
    return 0;
}
