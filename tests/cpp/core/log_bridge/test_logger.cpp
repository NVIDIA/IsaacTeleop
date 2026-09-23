// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// What only C++ can ask of the logger. Everything that depends on how
// local_sinks() read the environment is driven out-of-process from
// tests/python/core/logging_config, because that answer is a function-local
// static and there is one per process.

#include <catch2/catch_test_macros.hpp>
#include <log_bridge/logger.hpp>
#include <spdlog/common.h>
#include <spdlog/spdlog.h>

TEST_CASE("Logger::get returns one instance per name", "[unit]")
{
    auto first = isaaccapture::Logger::get("isaaccapture.test.Memoized");
    REQUIRE(isaaccapture::Logger::get("isaaccapture.test.Memoized") == first);
    REQUIRE(spdlog::get("isaaccapture.test.Memoized") == first);
    REQUIRE(isaaccapture::Logger::get("isaaccapture.test.Other") != first);
}

TEST_CASE("Logger leaves level filtering to sinks", "[unit]")
{
    REQUIRE(isaaccapture::Logger::get("isaaccapture.test.Level")->level() == spdlog::level::trace);
}

TEST_CASE("to_python_level matches logging_config's numbering", "[unit]")
{
    using isaaccapture::detail::to_python_level;
    REQUIRE(to_python_level(spdlog::level::trace) == 5);
    REQUIRE(to_python_level(spdlog::level::debug) == 10);
    REQUIRE(to_python_level(spdlog::level::info) == 20);
    REQUIRE(to_python_level(spdlog::level::warn) == 30);
    REQUIRE(to_python_level(spdlog::level::err) == 40);
    REQUIRE(to_python_level(spdlog::level::critical) == 50);
    REQUIRE(to_python_level(spdlog::level::off) == 20);
}
