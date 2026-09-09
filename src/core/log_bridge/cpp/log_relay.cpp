// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/log_bridge/log_relay.hpp"

#include "inc/log_bridge/logger.hpp"

#include <spdlog/spdlog.h>

#include <array>
#include <string_view>

#ifndef _WIN32
#    include <unistd.h>
#endif

namespace isaacteleop
{
namespace
{

// ThirdParty throughout: a relayed record has already cleared its origin
// process's threshold, so the logger it lands in here must not re-floor it at
// debug and drop the trace records the relay exists to carry.
void emit(std::string_view line, const std::string& fallback_logger_name)
{
    const auto relay_raw = [&] { Logger::get(fallback_logger_name, LoggerKind::ThirdParty)->debug("{}", line); };

    if (line.empty())
    {
        return;
    }
    if (line.front() != kRelayMarker)
    {
        relay_raw();
        return;
    }
    line.remove_prefix(1);
    const auto level_end = line.find(kRelaySeparator);
    if (level_end == std::string_view::npos)
    {
        relay_raw();
        return;
    }
    const auto name_end = line.find(kRelaySeparator, level_end + 1);
    if (name_end == std::string_view::npos)
    {
        relay_raw();
        return;
    }
    const auto level = spdlog::level::from_str(std::string(line.substr(0, level_end)));
    const std::string name(line.substr(level_end + 1, name_end - level_end - 1));
    Logger::get(name, LoggerKind::ThirdParty)->log(level, "{}", line.substr(name_end + 1));
}

} // namespace

void relay_logs(int fd, const std::string& fallback_logger_name)
{
#ifndef _WIN32
    std::string pending;
    std::array<char, 4096> buffer{};
    ssize_t count = 0;
    while ((count = ::read(fd, buffer.data(), buffer.size())) > 0)
    {
        pending.append(buffer.data(), static_cast<std::size_t>(count));
        std::size_t start = 0;
        for (auto end = pending.find('\n', start); end != std::string::npos; end = pending.find('\n', start))
        {
            emit(std::string_view(pending).substr(start, end - start), fallback_logger_name);
            start = end + 1;
        }
        pending.erase(0, start);
    }
    // A process killed mid-line still said something worth keeping.
    if (!pending.empty())
    {
        emit(pending, fallback_logger_name);
    }
    ::close(fd);
#endif
}

} // namespace isaacteleop
