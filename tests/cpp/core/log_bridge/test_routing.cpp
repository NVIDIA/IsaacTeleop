// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Where a C++ record goes, for each of the three states a process can be in.
// The Python half has the same kind of table in
// tests/python/core/logging_config/test_logging_config.py; this is the other
// end of the same contract. Both tables are plain comments on purpose: they are
// what a reviewer reads, and the assertions beside them are what fails. Keep
// them in step by hand -- do not generate either one, and do not add a
// drift-check.
//
// Where each row is asserted:
//
//   process state                   record goes to                asserted by
//   ------------------------------  ----------------------------  ----------------------------------
//   set_bridge_sink() has run       the bridge sink, and nothing   this file, "an installed bridge
//                                   else; the logger holds         replaces existing local sinks",
//                                   exactly that one sink          with a capturing stand-in
//
//   install_python_sink() has run   Python's logging module in     test_logging_config.py's
//                                   this same process              test_cpp_logger_reaches_python_
//                                                                  through_real_bridge, through
//                                                                  _log_bridge._emit_test_warning
//
//   ISAACTELEOP_LOG_SOCKET unset    the emitter's own stdout, and  test_logging_config.py's
//                                   a matching                     test_cpp_logger_without_socket_
//                                   <ts>.isaacteleop.<pid>.log     uses_own_console_and_file
//                                   under ISAACTELEOP_LOG_DIR
//
//   ISAACTELEOP_LOG_SOCKET set      the leader's Python logger     test_logging_config.py's
//                                   tree, and neither local        test_cpp_logger_reaches_the_
//                                   destination                    python_receiver, which stands up
//                                                                  a real receiver and also asserts
//                                                                  the two negatives
//
//   Python level numbering is the   n/a -- pure function          this file, "Python level
//   one both senders use                                          numbering is the one both senders
//                                                                 use": trace 5, debug 10, info 20,
//                                                                 warn 30, err 40, critical 50
//
// The three routes are ordered, not independent: Logger::get() consults the
// bridge before local_sinks(), so an installed bridge wins over a socket.
//
// The choice between the last two process states is made once per process, by a
// function-local static inside local_sinks(), so no single binary can exercise
// both: each of those rows runs log_bridge_emit_record -- the one-record
// executable under emit_record/ -- in a process of its own. Those two rows live
// in the Python suite because the same processes are what the receiver at the
// other end needs; running them from here as well would assert the same thing
// twice. The bridge row is done in-process here, because set_bridge_sink() is a
// documented seam on the public header rather than something only the pybind
// module can reach.
//
// Deliberately not covered here: raw C++ output -- std::cout, printf, a vendor
// library writing to fd 1/2. log_bridge never redirects a descriptor, so that
// text goes wherever the emitting process inherited fd 1/2 pointing. Two other
// places decide what that is, and each is pinned where the deciding code lives:
// for the host's own process, the routing matrix in the Python suite; for a
// process the plugin manager launched, whose fd 1 and fd 2 plugin.cpp sets
// between fork() and execvp(), test_plugin_process.cpp's "a launched plugin's
// stdio follows the published capture file".

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

//! Token the emitter logs and a parent looks for.
constexpr const char* kToken = "ROUTING-MATRIX-RECORD";

//! Records every message handed to it, so a test can assert what arrived.
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
    // SocketForwardSink and PythonBridgeSink both serialise through this, and
    // isaacteleop/logging_config/_core.py has to agree with it, or a forwarded
    // record changes severity on the way across.
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
