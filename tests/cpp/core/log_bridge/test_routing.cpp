// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Where a C++ record goes, for each of the three states a process can be in.
// The Python half has the same kind of table in
// tests/python/core/logging_config/test_logging_config.py; this is the other
// end of the same contract.
//
// What each case asserts:
//
//   case                            process state                 expected result
//   ------------------------------  ----------------------------  ----------------------------------
//   an installed bridge takes the   set_bridge_sink() has run     the record reaches the bridge sink
//   record ...                                                    and nothing else; the logger holds
//                                                                 exactly that one sink
//
//   with no socket the record       ISAACTELEOP_LOG_SOCKET        the record is on the emitter's own
//   reaches this process's console  unset                         stdout, and in a matching
//   and its own log file                                          <ts>.isaacteleop.<pid>.log under
//                                                                 ISAACTELEOP_LOG_DIR
//
//   with a socket set the record    ISAACTELEOP_LOG_SOCKET set    neither of those two: the forward
//   reaches neither local                                         sink has replaced the console and
//   destination                                                   file sinks. Where the record goes
//                                                                 *instead* is asserted by the Python
//                                                                 suite's
//                                                                 test_cpp_logger_reaches_the_python
//                                                                 _receiver, which stands up a real
//                                                                 receiver at the other end
//
//   Python level numbering is the   n/a -- pure function          trace 5, debug 10, info 20,
//   one both senders use                                          warn 30, err 40, critical 50
//
// The choice between the first two process states is made once per process, by
// a function-local static inside local_sinks(), so no single binary can
// exercise both: each case runs log_bridge_emit_record -- the one-record
// executable built beside this one -- with the environment it needs. The bridge
// case is done in-process, because set_bridge_sink() is a documented seam on
// the public header rather than something only the pybind module can reach.
//
// Deliberately not covered here: raw C++ output -- std::cout, printf, a
// vendor library writing to fd 1/2. This library never redirects a descriptor,
// so that text goes wherever the process inherited fd 1/2 pointing, and which
// file that turns out to be is a property of the Python side's capture. The
// matrix in the Python suite is where those rows live.

#include <catch2/catch_test_macros.hpp>
#include <log_bridge/logger.hpp>
#include <spdlog/details/log_msg.h>
#include <spdlog/sinks/base_sink.h>

#include <memory>
#include <mutex>
#include <string>
#include <vector>

#ifdef __linux__
#    include <cstdlib>
#    include <filesystem>
#    include <fstream>
#    include <unistd.h>
#endif

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

#ifdef __linux__

namespace
{

//! log_bridge_emit_record, which CMake builds into this executable's directory.
std::filesystem::path emitter_path()
{
    return std::filesystem::read_symlink("/proc/self/exe").parent_path() / "log_bridge_emit_record";
}

//! A directory nothing else writes to. The pid has to be in the name: without
//! it this is a fixed path under a world-writable /tmp, shared by every
//! concurrent run on the machine -- a second build directory's, or another
//! user's -- and the remove_all() below then either deletes that run's log file
//! out from under it or fails outright against a directory /tmp's sticky bit
//! will not let us remove.
std::filesystem::path fresh_dir(const std::string& tag)
{
    const auto dir =
        std::filesystem::temp_directory_path() / ("log_bridge_routing_" + tag + "_" + std::to_string(::getpid()));
    std::filesystem::remove_all(dir);
    std::filesystem::create_directories(dir);
    return dir;
}

//! Whether `path` contains `kToken`.
bool file_contains_token(const std::filesystem::path& path)
{
    std::ifstream file(path);
    for (std::string line; std::getline(file, line);)
    {
        if (line.find(kToken) != std::string::npos)
        {
            return true;
        }
    }
    return false;
}

//! Whether any ``*.log`` directly under `dir` contains `kToken`.
bool any_log_contains_token(const std::filesystem::path& dir)
{
    for (const auto& entry : std::filesystem::directory_iterator(dir))
    {
        if (entry.path().extension() != ".log")
        {
            continue;
        }
        if (file_contains_token(entry.path()))
        {
            return true;
        }
    }
    return false;
}

//! Emit one warning through a fresh process with `env_assignments` applied, its
//! console output collected into `console_path`; waits for it.
int run_emitter(const std::string& env_assignments, const std::filesystem::path& console_path)
{
    const std::string command = "env " + env_assignments + " \"" + emitter_path().string() +
                                "\" isaacteleop.log_bridge.test.routing warning " + kToken + " > \"" +
                                console_path.string() + "\" 2>&1";
    // Every path above is quoted: temp_directory_path() follows TMPDIR, which an
    // operator is free to point at a directory whose name contains a space.
    return std::system(command.c_str());
}

} // namespace

TEST_CASE("with no socket the record reaches this process's console and log file", "[log_bridge][routing]")
{
    const auto dir = fresh_dir("local");
    // Not a *.log name: any_log_contains_token() scans this same directory.
    const auto console = dir / "console.out";
    const int status = run_emitter("-u ISAACTELEOP_LOG_SOCKET ISAACTELEOP_LOG_DIR=\"" + dir.string() + "\"", console);

    CHECK(status == 0);
    CHECK(file_contains_token(console));
    CHECK(any_log_contains_token(dir));
    std::filesystem::remove_all(dir);
}

TEST_CASE("with a socket set the record reaches neither local destination", "[log_bridge][routing]")
{
    // The socket deliberately does not exist. Connecting is best-effort and the
    // record is dropped when it fails, which is what makes this a clean test of
    // the *selection*: the forward sink replaces the console and file sinks, so
    // the absence of both is the whole assertion and no receiver has to be stood
    // up to make it. The Python suite stands one up and asserts what arrives.
    const auto dir = fresh_dir("forward");
    const auto console = dir / "console.out";
    const auto socket_path = dir / "absent.sock";
    const int status = run_emitter(
        "ISAACTELEOP_LOG_SOCKET=\"" + socket_path.string() + "\" ISAACTELEOP_LOG_DIR=\"" + dir.string() + "\"", console);

    CHECK(status == 0);
    CHECK_FALSE(file_contains_token(console));
    CHECK_FALSE(any_log_contains_token(dir));
    std::filesystem::remove_all(dir);
}

#endif // __linux__

// Last on purpose: set_bridge_sink() re-points every logger already registered
// in this process, so anything asserting about sinks has to have run first.
TEST_CASE("an installed bridge takes the record and the local sinks do not", "[log_bridge][routing]")
{
    auto capture = std::make_shared<CapturingSink>();
    isaacteleop::detail::set_bridge_sink(capture);
    CHECK(isaacteleop::detail::bridge_sink() == capture);

    auto logger = isaacteleop::Logger::get("isaacteleop.log_bridge.test.bridged");
    REQUIRE(logger->sinks().size() == 1);
    CHECK(logger->sinks().front() == isaacteleop::detail::bridge_sink());

    logger->warn("{}", kToken);
    REQUIRE(capture->messages.size() == 1);
    CHECK(capture->messages.front() == kToken);
}
