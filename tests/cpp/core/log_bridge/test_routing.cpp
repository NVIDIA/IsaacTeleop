// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <log_bridge/logger.hpp>
#include <spdlog/details/log_msg.h>
#include <spdlog/sinks/base_sink.h>

#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace
{

constexpr const char* kToken = "ROUTING-MATRIX-RECORD";

class CapturingSink : public spdlog::sinks::base_sink<std::mutex>
{
public:
    std::vector<std::string> messages;

protected:
    void sink_it_(const spdlog::details::log_msg& msg) override
    {
        messages.emplace_back(msg.payload.data(), msg.payload.size());
    }

    void flush_() override
    {
    }
};

} // namespace

TEST_CASE("Python level numbering is the one both senders use", "[log_bridge][routing]")
{
    using isaacteleop::detail::to_python_level;
    CHECK(to_python_level(spdlog::level::trace) == 5);
    CHECK(to_python_level(spdlog::level::debug) == 10);
    CHECK(to_python_level(spdlog::level::info) == 20);
    CHECK(to_python_level(spdlog::level::warn) == 30);
    CHECK(to_python_level(spdlog::level::err) == 40);
    CHECK(to_python_level(spdlog::level::critical) == 50);
}

// set_bridge_sink() is process-global and has no reset operation, so keep this
// case last when running the Catch2 executable without CTest isolation.
TEST_CASE("an installed bridge replaces existing local sinks", "[log_bridge][routing]")
{
    auto logger = isaacteleop::Logger::get("isaacteleop.log_bridge.test.bridged");
    REQUIRE_FALSE(logger->sinks().empty());

    auto capture = std::make_shared<CapturingSink>();
    isaacteleop::detail::set_bridge_sink(capture);

    CHECK(isaacteleop::detail::bridge_sink() == capture);
    REQUIRE(logger->sinks().size() == 1);
    CHECK(logger->sinks().front() == capture);

    logger->warn("{}", kToken);
    REQUIRE(capture->messages.size() == 1);
    CHECK(capture->messages.front() == kToken);
}
