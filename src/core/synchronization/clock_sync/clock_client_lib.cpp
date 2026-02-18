// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "clock_sync/clock_client.hpp"

#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

// ============================================================================
// Factory
// ============================================================================

std::shared_ptr<ClockClient> ClockClient::Create(const std::string& server_ip,
                                                 uint16_t port,
                                                 MeasurementCallback callback,
                                                 ClockTranslator translator)
{
    auto client = std::shared_ptr<ClockClient>(new ClockClient());
    client->translator_ = std::move(translator);
    client->callback_ = std::move(callback);
    client->initialize(server_ip, port);
    return client;
}

// ============================================================================
// Lifecycle
// ============================================================================

void ClockClient::initialize(const std::string& server_ip, uint16_t port)
{
    ensure_winsock();

    sock_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock_ == kInvalidSocket)
    {
        throw std::runtime_error("[ClockClient] Failed to create socket");
    }

    set_recv_timeout(sock_, 100);

    std::memset(&server_addr_, 0, sizeof(server_addr_));
    server_addr_.sin_family = AF_INET;
    server_addr_.sin_port = htons(port);
    if (inet_pton(AF_INET, server_ip.c_str(), &server_addr_.sin_addr) <= 0)
    {
        close_socket(sock_);
        sock_ = kInvalidSocket;
        throw std::runtime_error("[ClockClient] Invalid server address: " + server_ip);
    }

    alive_.store(true, std::memory_order_release);
    receiver_ = std::thread(&ClockClient::receiver_loop, this);
}

ClockClient::~ClockClient()
{
    stop();

    alive_.store(false, std::memory_order_release);
    if (receiver_.joinable())
    {
        receiver_.join();
    }

    if (sock_ != kInvalidSocket)
    {
        close_socket(sock_);
    }
}

// ============================================================================
// Callback
// ============================================================================

void ClockClient::set_callback(MeasurementCallback cb)
{
    std::lock_guard<std::mutex> lock(callback_mutex_);
    callback_ = std::move(cb);
}

// ============================================================================
// Non-blocking ping
// ============================================================================

void ClockClient::ping()
{
    uint8_t buf[sizeof(ClockPacket)];
    ClockPacket req;
    req.t1 = get_monotonic_ns();
    req.serialize(buf);

    sendto(sock_, reinterpret_cast<const char*>(buf), sizeof(ClockPacket), 0,
           reinterpret_cast<sockaddr*>(&server_addr_), sizeof(server_addr_));
}

// ============================================================================
// Receiver thread
// ============================================================================

void ClockClient::receiver_loop()
{
    uint8_t buf[sizeof(ClockPacket)];

    while (alive_.load(std::memory_order_acquire))
    {
        sockaddr_in from{};
        socklen_t from_len = sizeof(from);
        ssize_t n =
            recvfrom(sock_, reinterpret_cast<char*>(buf), sizeof(buf), 0, reinterpret_cast<sockaddr*>(&from), &from_len);

        clock_ns_t t4 = get_monotonic_ns();

        if (n < 0)
        {
            continue;
        }

        if (static_cast<size_t>(n) < sizeof(ClockPacket))
        {
            continue;
        }

        auto reply = ClockPacket::deserialize(buf);
        ClockMeasurement m{ reply.t1, reply.t2, reply.t3, t4 };

        if (translator_)
        {
            m.t1 = translator_(m.t1);
            m.t4 = translator_(m.t4);
        }

        MeasurementCallback cb;
        {
            std::lock_guard<std::mutex> lock(callback_mutex_);
            cb = callback_;
        }

        if (cb)
        {
            cb(m);
        }
    }
}

// ============================================================================
// Periodic sender
// ============================================================================

void ClockClient::start(int interval_ms, int count)
{
    if (sending_.load(std::memory_order_relaxed))
    {
        throw std::runtime_error("[ClockClient] Periodic pinging already active");
    }

    sending_.store(true, std::memory_order_release);
    sender_ = std::thread(&ClockClient::sender_loop, this, interval_ms, count);
}

void ClockClient::stop()
{
    sending_.store(false, std::memory_order_release);
    if (sender_.joinable())
    {
        sender_.join();
    }
}

void ClockClient::sender_loop(int interval_ms, int count)
{
    int done = 0;

    while (sending_.load(std::memory_order_acquire) && (count == 0 || done < count))
    {
        ping();
        ++done;

        if (sending_.load(std::memory_order_acquire) && (count == 0 || done < count))
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
        }
    }

    sending_.store(false, std::memory_order_release);
}

} // namespace core
