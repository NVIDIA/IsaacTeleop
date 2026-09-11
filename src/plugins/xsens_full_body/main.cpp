// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "plugin_options.hpp"
#include "xsens_full_body_plugin.hpp"

#include <atomic>
#include <csignal>
#include <cstdint>
#include <iostream>
#include <string>

using namespace plugins::xsens_full_body;

namespace
{

constexpr uint64_t STATS_EVERY = 250;

//! Atomic rather than volatile sig_atomic_t: the plugin observes this from inside its recovery
//! backoffs, so a stop request lands during an outage instead of waiting the budget out.
std::atomic<bool> g_stop{ false };

extern "C" void handle_signal(int)
{
    g_stop.store(true, std::memory_order_relaxed);
}

void usage(const char* argv0)
{
    const XsensFullBodyOptions defaults;
    std::cerr << "Usage: " << argv0 << " [options]\n\n"
              << "Receives Xsens MVN Studio's Isaac Teleop UDP stream and republishes it as an\n"
              << "Isaac Teleop tensor collection, readable via the `body.xsens` vendor.\n\n"
              << "Options:\n"
              << "  --collection-id=ID        Tensor collection id (default: " << defaults.collection_id << ")\n"
              << "  --address=ADDR            Interface to bind, literal IPv4 (default: " << defaults.bind_address
              << ")\n"
              << "  --port=N                  UDP port to listen on (default: " << defaults.udp_port << ")\n"
              << "  --max-flatbuffer-size=N   Max serialized frame size, must match the reader\n"
              << "                            (default: " << defaults.max_flatbuffer_size << ")\n"
              << "  --help                    Show this message\n\n"
              << "The defaults match MVN's \"Isaac Teleop\" preset. `--address=127.0.0.1` confines the\n"
              << "pusher to loopback; the default accepts the stream on every interface.\n\n"
              << "Deprecated: the positional form `[collection_id] [udp_port] [max_flatbuffer_size]`\n"
              << "is still accepted, but cannot be mixed with the flags above.\n";
}

//! Every counter, on one line. Printed periodically and once more on exit -- including the
//! unrecoverable-outage exit, so a pusher that gave up still says what it saw first.
void print_stats(const XsensFullBodyStats& s, const char* prefix)
{
    std::cout << prefix << "delivered=" << s.delivered << " seq=" << s.last_seq << " size=" << s.last_size
              << " fnv1a64=0x" << std::hex << s.last_hash << std::dec << " malformed=" << s.dropped_malformed
              << " unverified=" << s.dropped_unverified << " stale=" << s.dropped_stale
              << " truncated=" << s.dropped_truncated << " gapEvents=" << s.sequence_gap_events
              << " seqSkipped=" << s.sequence_numbers_skipped << " resets=" << s.session_resets
              << " rewinds=" << s.timeline_rewinds << " nonWholeMs=" << s.non_whole_ms_samples
              << " socketRecoveries=" << s.socket_recoveries << " socketRecoveryFailures=" << s.socket_recovery_failures
              << " pushFailures=" << s.push_failures << " sessionRecoveries=" << s.session_recoveries << std::endl;
}

} // namespace

int main(int argc, char** argv)
try
{
    XsensFullBodyOptions options;
    std::string parse_error;
    switch (parse_options(argc, argv, options, parse_error))
    {
    case ParseOutcome::HelpRequested:
        usage(argv[0]);
        return 0;
    case ParseOutcome::Error:
        std::cerr << argv[0] << ": " << parse_error << "\n\n";
        usage(argv[0]);
        return 1;
    case ParseOutcome::Ok:
        break;
    }

    if (options.used_legacy_positionals)
    {
        std::cerr << argv[0] << ": warning: the positional argument form is deprecated; use"
                  << " --collection-id=, --port= and --max-flatbuffer-size= instead" << std::endl;
    }

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    std::cout << "Xsens Full Body Pusher (collection: " << options.collection_id << ", tensor: full_body_pose"
              << ", udp: " << options.bind_address << ":" << options.udp_port
              << ", max_flatbuffer_size: " << options.max_flatbuffer_size << ")" << std::endl;

    XsensFullBodyPlugin plugin(options);

    std::cout << "listening on " << options.bind_address << ":" << options.udp_port << " -> push_buffer" << std::endl;
    std::cout << "In MVN Studio: Options -> Network Streamer -> preset \"Isaac Teleop\", tick the row, press Play."
              << std::endl;

    // A broken socket or a restarted CloudXR runtime is recovered inside update(). It only throws
    // once a retry budget is exhausted, which is the operator-restart case -- and even then the
    // counters go out, because they are usually the only record of what led up to it.
    int exit_code = 0;
    uint64_t since_stats = 0;
    try
    {
        while (!g_stop.load(std::memory_order_relaxed))
        {
            if (!plugin.update(g_stop))
            {
                continue;
            }
            if (++since_stats >= STATS_EVERY)
            {
                since_stats = 0;
                print_stats(plugin.stats(), "[XsensFullBody] ");
            }
        }
    }
    catch (const std::exception& e)
    {
        std::cerr << "\n" << argv[0] << ": " << e.what() << std::endl;
        exit_code = 1;
    }

    print_stats(plugin.stats(), "\nstopped: ");
    return exit_code;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error" << std::endl;
    return 1;
}
