// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file main.cpp
 * @brief j-mex AgileMaster device plugin: streams a MOXI channel's robot joint angles as
 *        ``JointStateOutput`` over the OpenXR tensor transport.
 *
 * Usage: ``jmex_plugin [--channel=1] [--collection-id=jmex]``. There is no synthetic backend:
 * building needs the MOXI Receiver SDK and running needs MOXI Player. See README.md.
 */

#include <jmex/joint_state_publisher.hpp>
#include <jmex/receiver_session.hpp>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>

#include <chrono>
#include <cstddef>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

using namespace plugins::jmex;

namespace
{

// MOXI Player runs at 60 Hz. Polling several times faster keeps the delay between a frame landing
// and it being published well under one frame; nothing is published twice.
constexpr int kPollHz = 240;

bool starts_with(const std::string& value, const std::string& prefix)
{
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

struct PluginArgs
{
    int channel = 1;
    std::string collection_id = "jmex";
};

//! Parse named arguments, last one wins.
//!
//! Named rather than positional because the PluginManager injects ``--plugin-root-id=<id>`` ahead of
//! everything plugin.yaml and PluginConfig supply: positional arguments would all shift by one and
//! the plugin would come up on a channel nobody asked for, silently.
PluginArgs parse_args(int argc, char** argv)
{
    PluginArgs args;

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (starts_with(arg, "--channel="))
        {
            const std::string value = arg.substr(std::string("--channel=").size());
            try
            {
                // Reject partially parsed values; otherwise "2.9" silently selects channel 2,
                // making a channel mismatch look like Player never connected.
                std::size_t consumed = 0;
                args.channel = std::stoi(value, &consumed);
                if (consumed != value.size())
                {
                    throw std::invalid_argument("trailing characters after the number");
                }
            }
            catch (const std::exception&)
            {
                // A silent default would pair with nothing and look like Player never started.
                throw std::runtime_error("--channel= takes a number, got '" + value + "'");
            }
        }
        else if (starts_with(arg, "--collection-id="))
        {
            args.collection_id = arg.substr(std::string("--collection-id=").size());
        }
        else if (starts_with(arg, "--plugin-root-id="))
        {
            // Injected by the PluginManager; not used by this plugin.
        }
        else
        {
            std::cerr << "jmex: ignoring unknown argument '" << arg << "'" << std::endl;
        }
    }

    return args;
}

} // namespace

int main(int argc, char** argv)
try
{
    const PluginArgs args = parse_args(argc, argv);
    const int channel = args.channel;
    const std::string collection_id = args.collection_id;

    std::cout << "j-mex AgileMaster plugin (channel: " << channel << ", collection: " << collection_id
              << ", SDK: " << moxi_sdk_version() << ")" << std::endl;

    // OpenXR first: a missing runtime is the common setup mistake, and failing on it before the
    // MOXI receiver starts means we never take the process-global TCP port just to give it back.
    auto oxr_session = std::make_shared<core::OpenXRSession>("JmexPlugin", core::SchemaPusher::get_required_extensions());
    JointStatePublisher publisher(oxr_session->get_handles(), collection_id);

    // The receiver is the TCP server; MOXI Player connects in. Starting before the Player is up is
    // the normal case, not an error.
    ReceiverSession receiver(channel);

    std::cout << "Waiting for MOXI Player to pair on channel " << channel << "..." << std::endl;

    const auto poll_interval = std::chrono::nanoseconds(1000000000 / kPollHz);
    const auto program_start = std::chrono::steady_clock::now();
    int64_t poll_count = 0;
    int64_t published = 0;

    while (true)
    {
        if (receiver.poll())
        {
            publisher.publish(receiver);
            if (published == 0)
            {
                std::cout << "Streaming: " << receiver.actuated_joints().size() << " joints on collection '"
                          << collection_id << "'" << std::endl;
            }
            ++published;
        }
        ++poll_count;
        std::this_thread::sleep_until(program_start + poll_interval * poll_count);
    }

    return 0;
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
