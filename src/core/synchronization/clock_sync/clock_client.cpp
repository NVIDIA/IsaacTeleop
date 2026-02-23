// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "clock_sync/clock_client.hpp"

#include <condition_variable>
#include <csignal>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <vector>

namespace
{

volatile sig_atomic_t g_running = 1;

void signal_handler(int /*sig*/)
{
    g_running = 0;
}

void print_header()
{
    std::cout << std::left << std::setw(8) << "seq" << std::setw(18) << "rtt_us" << std::setw(18) << "offset_us"
              << std::setw(18) << "t1_ns" << std::setw(18) << "t2_ns" << std::setw(18) << "t3_ns" << std::setw(18)
              << "t4_ns"
              << "\n";
    std::cout << std::string(116, '-') << "\n";
}

void print_measurement(uint64_t seq, const core::ClockMeasurement& m)
{
    std::cout << std::left << std::setw(8) << seq << std::setw(18) << std::fixed << std::setprecision(3)
              << core::ns_to_sec(m.rtt()) * 1e6 << std::setw(18) << core::ns_to_sec(m.offset()) * 1e6 << std::setw(18)
              << m.t1 << std::setw(18) << m.t2 << std::setw(18) << m.t3 << std::setw(18) << m.t4 << "\n";
}

void print_summary(const std::vector<core::ClockMeasurement>& measurements, uint64_t sent)
{
    if (measurements.empty())
        return;

    core::clock_ns_t min_rtt = measurements[0].rtt();
    core::clock_ns_t max_rtt = min_rtt;
    double sum_rtt = 0;
    double sum_offset = 0;

    for (const auto& m : measurements)
    {
        core::clock_ns_t r = m.rtt();
        if (r < min_rtt)
            min_rtt = r;
        if (r > max_rtt)
            max_rtt = r;
        sum_rtt += static_cast<double>(r);
        sum_offset += static_cast<double>(m.offset());
    }

    double avg_rtt = sum_rtt / static_cast<double>(measurements.size());
    double avg_offset = sum_offset / static_cast<double>(measurements.size());
    uint64_t lost = sent - measurements.size();

    std::cout << "\n--- Summary ---\n";
    std::cout << "Packets: " << sent << " sent, " << measurements.size() << " received, " << lost << " lost\n";
    std::cout << std::fixed << std::setprecision(3);
    std::cout << "RTT (us):    min=" << core::ns_to_sec(min_rtt) * 1e6 << "  avg=" << avg_rtt / 1e3
              << "  max=" << core::ns_to_sec(max_rtt) * 1e6 << "\n";
    std::cout << "Offset (us): avg=" << avg_offset / 1e3 << "\n";
}

} // namespace

int main(int argc, char* argv[])
{
    if (argc < 2)
    {
        std::cerr << "Usage: clock_client <server_ip> [port] [interval_ms] [count]\n"
                  << "  Client uses CLOCK_MONOTONIC; server uses CLOCK_MONOTONIC_RAW.\n";
        return 1;
    }

    const char* server_ip = argv[1];
    uint16_t port = (argc > 2) ? static_cast<uint16_t>(std::atoi(argv[2])) : core::kDefaultClockPort;
    int interval_ms = (argc > 3) ? std::atoi(argv[3]) : 1000;
    int count = (argc > 4) ? std::atoi(argv[4]) : 0;

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::vector<core::ClockMeasurement> measurements;
    std::mutex mu;
    std::condition_variable cv;
    uint64_t seq = 0;

    auto on_measurement = [&](const core::ClockMeasurement& m)
    {
        std::lock_guard<std::mutex> lock(mu);
        measurements.push_back(m);
        print_measurement(seq, m);
        ++seq;
        cv.notify_one();
    };

    std::shared_ptr<core::ClockClient> client;
    try
    {
        client = core::ClockClient::Create(server_ip, port, on_measurement);
    }
    catch (const std::exception& e)
    {
        std::cerr << e.what() << std::endl;
        return 1;
    }

    std::cout << "[ClockClient] Pinging " << server_ip << ":" << port << " every " << interval_ms << " ms"
              << " (client: CLOCK_MONOTONIC, server: CLOCK_MONOTONIC_RAW)\n\n";

    print_header();

    uint64_t sent = 0;

    if (count > 0)
    {
        client->start(interval_ms, count);
        sent = static_cast<uint64_t>(count);

        std::unique_lock<std::mutex> lock(mu);
        cv.wait_for(lock, std::chrono::milliseconds(count * interval_ms + 2000),
                    [&] { return seq >= static_cast<uint64_t>(count) || !g_running; });
    }
    else
    {
        client->start(interval_ms, 0);

        while (g_running)
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        client->stop();
        sent = seq + 1;
    }

    {
        std::lock_guard<std::mutex> lock(mu);
        print_summary(measurements, sent);
    }

    return 0;
}
