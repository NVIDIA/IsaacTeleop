// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// A logging process with no interpreter, which is what a standalone plugin
// executable is. local_sinks() resolves the environment once per process, so each
// permutation the suite covers needs a fresh one of these rather than another case
// in a long-lived test binary. Driven from tests/python/core/logging_config.

#include <log_bridge/logger.hpp>
#include <spdlog/common.h>

#include <chrono>
#include <cstdlib>
#include <string>
#include <thread>
#include <unistd.h>

namespace
{

// The six names isaaccapture.logging_config uses. spdlog's own "warn"/"err"
// spellings are not accepted anywhere in this tree.
spdlog::level::level_enum parse_level(const std::string& name)
{
    if (name == "trace")
    {
        return spdlog::level::trace;
    }
    if (name == "debug")
    {
        return spdlog::level::debug;
    }
    if (name == "warning")
    {
        return spdlog::level::warn;
    }
    if (name == "error")
    {
        return spdlog::level::err;
    }
    if (name == "critical")
    {
        return spdlog::level::critical;
    }
    return spdlog::level::info;
}

// A vendor library's own diagnostics: straight to the descriptor, past every logger.
void write_raw(int fd, const std::string& text)
{
    std::size_t written = 0;
    while (written < text.size())
    {
        const ssize_t n = ::write(fd, text.data() + written, text.size() - written);
        if (n <= 0)
        {
            return;
        }
        written += static_cast<std::size_t>(n);
    }
}

} // namespace

int main(int argc, char** argv)
{
    const std::string command = argc > 1 ? argv[1] : "";

    // Trailing arguments are ignored: a plugin launcher appends its own
    // --plugin-root-id to whatever plugin.yaml asked for.
    if (command == "raw" && argc >= 4)
    {
        const std::string text = std::string(argv[2]) + "\n";
        write_raw(STDOUT_FILENO, text);
        write_raw(STDERR_FILENO, text);
        std::this_thread::sleep_for(std::chrono::milliseconds(std::atoi(argv[3])));
        return 0;
    }

    if (command == "spin" && argc == 5)
    {
        auto logger = isaaccapture::Logger::get(argv[2]);
        const int count = std::atoi(argv[3]);
        const int interval_ms = std::atoi(argv[4]);
        for (int i = 0; i < count; ++i)
        {
            logger->info("spin {}", i);
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
        }
        return 0;
    }

    if ((command == "emit" || command == "abort") && argc >= 5 && (argc - 3) % 2 == 0)
    {
        auto logger = isaaccapture::Logger::get(argv[2]);
        for (int i = 3; i + 1 < argc; i += 2)
        {
            logger->log(parse_level(argv[i]), "{}", argv[i + 1]);
        }
        if (command == "abort")
        {
            // Deliberately unflushed: what the leader must already hold is what
            // SocketForwardSink sent synchronously from sink_it_.
            std::abort();
        }
        logger->flush();
        return 0;
    }

    write_raw(STDERR_FILENO,
              "usage: emit|abort <logger> (<level> <message>)...\n"
              "       spin <logger> <count> <interval_ms>\n"
              "       raw <text> <hold_ms>\n");
    return 2;
}
