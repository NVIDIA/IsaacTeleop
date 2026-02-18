// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "clock_sync/clock_types.hpp"
#include "clock_sync/platform.hpp"

#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>

namespace
{

volatile sig_atomic_t g_running = 1;

void signal_handler(int /*sig*/)
{
    g_running = 0;
}

} // namespace

int main(int argc, char* argv[])
{
    uint16_t port = core::kDefaultClockPort;
    if (argc > 1)
    {
        port = static_cast<uint16_t>(std::atoi(argv[1]));
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    core::ensure_winsock();

    core::socket_t sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock == core::kInvalidSocket)
    {
        std::cerr << "[ClockServer] Failed to create socket" << std::endl;
        return 1;
    }

#ifdef _WIN32
    char opt = 1;
#else
    int opt = 1;
#endif
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
    {
        std::cerr << "[ClockServer] Failed to bind to port " << port << std::endl;
        core::close_socket(sock);
        return 1;
    }

#ifdef _WIN32
    std::cout << "[ClockServer] Listening on UDP port " << port << " (QPC)" << std::endl;
#else
    std::cout << "[ClockServer] Listening on UDP port " << port << " (CLOCK_MONOTONIC_RAW)" << std::endl;
#endif

    uint8_t buf[sizeof(core::ClockPacket)];
    sockaddr_in client_addr{};
    socklen_t client_len = sizeof(client_addr);

    while (g_running)
    {
        auto n = recvfrom(
            sock, reinterpret_cast<char*>(buf), sizeof(buf), 0, reinterpret_cast<sockaddr*>(&client_addr), &client_len);

        core::clock_ns_t t2 = core::get_monotonic_raw_ns();

        if (n < 0)
        {
            if (core::is_socket_interrupted_error())
                continue;
            std::cerr << "[ClockServer] recvfrom error" << std::endl;
            continue;
        }

        if (static_cast<size_t>(n) < sizeof(core::ClockPacket))
        {
            std::cerr << "[ClockServer] Ignoring short packet (" << n << " bytes)" << std::endl;
            continue;
        }

        auto pkt = core::ClockPacket::deserialize(buf);
        pkt.t2 = t2;

        pkt.t3 = core::get_monotonic_raw_ns();
        pkt.serialize(buf);

        sendto(sock, reinterpret_cast<const char*>(buf), sizeof(core::ClockPacket), 0,
               reinterpret_cast<sockaddr*>(&client_addr), client_len);
    }

    std::cout << "\n[ClockServer] Shutting down." << std::endl;
    core::close_socket(sock);
    return 0;
}
