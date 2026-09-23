// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// What only C++ can ask of the logger. Everything that depends on how
// local_sinks() read the environment is driven out-of-process from
// tests/python/core/logging_config, because that answer is a function-local
// static and there is one per process.

#include <catch2/catch_test_macros.hpp>
#include <log_bridge/logger.hpp>
#include <spdlog/common.h>
#include <spdlog/sinks/base_sink.h>
#include <spdlog/spdlog.h>

#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace
{

// Stands in for PythonBridgeSink, which differs only in where the record goes;
// this library carries no pybind11 and must not learn about it here.
class RecordingSink : public spdlog::sinks::base_sink<std::mutex>
{
public:
    std::vector<std::string> names;

protected:
    void sink_it_(const spdlog::details::log_msg& msg) override
    {
        names.emplace_back(msg.logger_name.data(), msg.logger_name.size());
    }

    void flush_() override
    {
    }
};

} // namespace

TEST_CASE("Logger::get returns one instance per name", "[unit]")
{
    auto first = isaacteleop::Logger::get("isaacteleop.test.Memoized");
    REQUIRE(isaacteleop::Logger::get("isaacteleop.test.Memoized") == first);
    REQUIRE(spdlog::get("isaacteleop.test.Memoized") == first);
    REQUIRE(isaacteleop::Logger::get("isaacteleop.test.Other") != first);
}

TEST_CASE("LoggerKind decides the starting level, and only at creation", "[unit]")
{
    REQUIRE(isaacteleop::Logger::get("isaacteleop.test.App")->level() == spdlog::level::debug);
    REQUIRE(isaacteleop::Logger::get("isaacteleop.test.Vendor", isaacteleop::LoggerKind::ThirdParty)->level() ==
            spdlog::level::trace);
    // Memoized on the name alone, so a later call's kind is ignored -- vendor
    // chatter cannot be turned on by asking for the same logger twice.
    REQUIRE(isaacteleop::Logger::get("isaacteleop.test.App", isaacteleop::LoggerKind::ThirdParty)->level() ==
            spdlog::level::debug);
}

TEST_CASE("to_python_level matches logging_config's numbering", "[unit]")
{
    using isaacteleop::detail::to_python_level;
    REQUIRE(to_python_level(spdlog::level::trace) == 5);
    REQUIRE(to_python_level(spdlog::level::debug) == 10);
    REQUIRE(to_python_level(spdlog::level::info) == 20);
    REQUIRE(to_python_level(spdlog::level::warn) == 30);
    REQUIRE(to_python_level(spdlog::level::err) == 40);
    REQUIRE(to_python_level(spdlog::level::critical) == 50);
    REQUIRE(to_python_level(spdlog::level::off) == 20);
}

// Last in the file: the bridge pointer is process-wide and nothing undoes it.
TEST_CASE("set_bridge_sink replaces the sinks of existing and future loggers", "[unit]")
{
    auto before = isaacteleop::Logger::get("isaacteleop.test.Before");
    auto sink = std::make_shared<RecordingSink>();
    isaacteleop::detail::set_bridge_sink(sink);
    auto after = isaacteleop::Logger::get("isaacteleop.test.After");

    // Replaced, not added to: a bridged record is formatted once, by the far side.
    REQUIRE(before->sinks().size() == 1);
    REQUIRE(after->sinks().size() == 1);

    before->info("one");
    after->info("two");
    REQUIRE(sink->names == std::vector<std::string>{ "isaacteleop.test.Before", "isaacteleop.test.After" });
}
