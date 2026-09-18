// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <plugin_manager/plugin.hpp>

#include <chrono>
#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <unistd.h>

namespace
{

constexpr auto PROCESS_TIMEOUT = std::chrono::seconds(3);

core::ProcessSnapshot wait_for_terminal(core::Plugin& plugin)
{
    const auto deadline = std::chrono::steady_clock::now() + PROCESS_TIMEOUT;
    core::ProcessSnapshot snapshot;
    do
    {
        snapshot = plugin.get_process_snapshot();
        if (snapshot.state != core::ProcessState::RUNNING)
        {
            return snapshot;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    } while (std::chrono::steady_clock::now() < deadline);

    FAIL("plugin process did not terminate before timeout");
    return snapshot;
}

//! Published by isaacteleop.logging_config so a process with no interpreter can
//! open the session's capture file; read by plugin.cpp before it forks.
constexpr const char* kCaptureFileEnv = "ISAACTELEOP_NATIVE_CAPTURE_FILE";

std::string read_file(const std::filesystem::path& path)
{
    std::ifstream file(path);
    return std::string(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
}

std::string health_error(core::Plugin& plugin)
{
    try
    {
        plugin.check_health();
        return {};
    }
    catch (const core::PluginCrashException& error)
    {
        return error.what();
    }
}

} // namespace

TEST_CASE("process snapshot reports a running plugin", "[plugin_manager][process]")
{
    core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "wait" });
    const core::ProcessSnapshot snapshot = plugin.get_process_snapshot();

    REQUIRE(snapshot.state == core::ProcessState::RUNNING);
    REQUIRE(snapshot.reason == core::ProcessReason::NONE);
    REQUIRE(snapshot.pid > 0);
    REQUIRE_NOTHROW(plugin.check_health());
}

TEST_CASE("terminal process snapshots and health checks are deterministic", "[plugin_manager][process]")
{
    SECTION("clean exit remains a non-error")
    {
        core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "exit", "0", "250" });
        const core::ProcessSnapshot first = wait_for_terminal(plugin);
        const core::ProcessSnapshot second = plugin.get_process_snapshot();

        REQUIRE(first.state == core::ProcessState::EXITED);
        REQUIRE(first.reason == core::ProcessReason::CLEAN_EXIT);
        REQUIRE(first.exit_code == 0);
        REQUIRE(first.pid > 0);
        REQUIRE(second.exit_code == first.exit_code);
        REQUIRE_NOTHROW(plugin.check_health());
        REQUIRE_NOTHROW(plugin.stop());
        REQUIRE(plugin.get_process_snapshot().state == core::ProcessState::EXITED);
    }

    SECTION("nonzero exit throws the cached error on every check")
    {
        core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "exit", "7", "250" });
        const core::ProcessSnapshot first = wait_for_terminal(plugin);
        const std::string first_error = health_error(plugin);
        const std::string second_error = health_error(plugin);
        const core::ProcessSnapshot second = plugin.get_process_snapshot();

        REQUIRE(first.state == core::ProcessState::EXITED);
        REQUIRE(first.reason == core::ProcessReason::NONZERO_EXIT);
        REQUIRE(first.exit_code == 7);
        REQUIRE(first.error == "Plugin process unexpectedly exited with code 7");
        REQUIRE(first_error == first.error);
        REQUIRE(second_error == first_error);
        REQUIRE(second.error == first.error);
    }

    SECTION("signal exit throws the cached error on every check")
    {
        core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "signal", std::to_string(SIGTERM), "250" });
        const core::ProcessSnapshot first = wait_for_terminal(plugin);
        const std::string first_error = health_error(plugin);
        const std::string second_error = health_error(plugin);
        const core::ProcessSnapshot second = plugin.get_process_snapshot();

        REQUIRE(first.state == core::ProcessState::SIGNALED);
        REQUIRE(first.reason == core::ProcessReason::SIGNAL);
        REQUIRE(first.term_signal == SIGTERM);
        REQUIRE_FALSE(first.error.empty());
        REQUIRE(first_error == first.error);
        REQUIRE(second_error == first_error);
        REQUIRE(second.term_signal == first.term_signal);
    }
}

TEST_CASE("explicit stop is cached and non-failing", "[plugin_manager][process]")
{
    core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "wait" });
    const std::int64_t pid = plugin.get_process_snapshot().pid;

    REQUIRE_NOTHROW(plugin.stop());
    const core::ProcessSnapshot first = plugin.get_process_snapshot();
    REQUIRE(first.state == core::ProcessState::STOPPED);
    REQUIRE(first.reason == core::ProcessReason::EXPLICIT_STOP);
    REQUIRE(first.pid == pid);
    REQUIRE_FALSE(first.exit_code.has_value());
    REQUIRE_FALSE(first.term_signal.has_value());
    REQUIRE_NOTHROW(plugin.check_health());

    REQUIRE_NOTHROW(plugin.stop());
    const core::ProcessSnapshot second = plugin.get_process_snapshot();
    REQUIRE(second.state == first.state);
    REQUIRE(second.reason == first.reason);
}


// A plugin is a process this library launched, so its descriptors are ours to
// set -- that is the half of the logging design that keeps vendor output off the
// terminal without the parent ever rebinding its own fd 1 and fd 2. plugin.cpp
// does it between fork() and execvp(), where only async-signal-safe calls are
// legal, and nothing else exercises that window.
TEST_CASE("a launched plugin's stdio follows the published capture file", "[plugin_manager][process][logging]")
{
    const auto capture =
        std::filesystem::temp_directory_path() / ("plugin_capture_" + std::to_string(::getpid()) + ".log");
    std::filesystem::remove(capture);

    SECTION("published: both of the child's descriptors land in that file")
    {
        ::setenv(kCaptureFileEnv, capture.string().c_str(), 1);
        {
            core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "write" });
            const core::ProcessSnapshot snapshot = wait_for_terminal(plugin);
            REQUIRE(snapshot.exit_code == 0);
        }
        ::unsetenv(kCaptureFileEnv);

        REQUIRE(std::filesystem::exists(capture));
        const std::string contents = read_file(capture);
        CHECK(contents.find("PLUGIN-STDOUT") != std::string::npos);
        CHECK(contents.find("PLUGIN-STDERR") != std::string::npos);
    }

    SECTION("not published: the child inherits ours and no file is created")
    {
        // The two marker lines go to this test binary's own stdout and stderr
        // here, which is the correct fallback: with nowhere published, a plugin
        // must keep the stdio it inherited rather than lose its output.
        ::unsetenv(kCaptureFileEnv);
        {
            core::Plugin plugin(PLUGIN_MANAGER_TEST_PROCESS, "", "test-root", { "write" });
            const core::ProcessSnapshot snapshot = wait_for_terminal(plugin);
            REQUIRE(snapshot.exit_code == 0);
        }

        CHECK_FALSE(std::filesystem::exists(capture));
    }

    std::filesystem::remove(capture);
}
