// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <plugin_manager/plugin.hpp>

#include <chrono>
#include <csignal>
#include <string>
#include <thread>

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
