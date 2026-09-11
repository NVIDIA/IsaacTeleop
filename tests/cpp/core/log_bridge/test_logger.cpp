// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <log_bridge/logger.hpp>

TEST_CASE("Logger::get memoizes by name", "[log_bridge][logger]")
{
    auto a = isaacteleop::Logger::get("isaacteleop.log_bridge.test.memoize");
    auto b = isaacteleop::Logger::get("isaacteleop.log_bridge.test.memoize");
    CHECK(a == b);
    CHECK(a->name() == "isaacteleop.log_bridge.test.memoize");
}

TEST_CASE("Logger::get defaults Application loggers to debug", "[log_bridge][logger]")
{
    auto logger =
        isaacteleop::Logger::get("isaacteleop.log_bridge.test.application_level", isaacteleop::LoggerKind::Application);
    CHECK(logger->level() == spdlog::level::debug);
}

TEST_CASE("Logger::get defaults ThirdParty loggers to trace", "[log_bridge][logger]")
{
    auto logger =
        isaacteleop::Logger::get("isaacteleop.log_bridge.test.thirdparty_level", isaacteleop::LoggerKind::ThirdParty);
    CHECK(logger->level() == spdlog::level::trace);
}

TEST_CASE("Logger::get ignores kind for an already-registered logger", "[log_bridge][logger]")
{
    // The first call's kind wins -- matches spdlog's own registry semantics
    // (spdlog::get() returns the existing instance regardless of how a
    // later call would have constructed one).
    auto first =
        isaacteleop::Logger::get("isaacteleop.log_bridge.test.kind_sticky", isaacteleop::LoggerKind::Application);
    auto second =
        isaacteleop::Logger::get("isaacteleop.log_bridge.test.kind_sticky", isaacteleop::LoggerKind::ThirdParty);
    CHECK(first == second);
    CHECK(second->level() == spdlog::level::debug);
}
