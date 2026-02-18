// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "clock_types.hpp"
#include "platform.hpp"

#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace core
{

/*!
 * @brief Asynchronous UDP client for measuring clock offset and RTT against a
 *        ClockServer.
 *
 * Internally the client always timestamps with CLOCK_MONOTONIC (QPC on
 * Windows).  An optional ClockTranslator can be provided to convert the
 * client-side timestamps (t1, t4) into another time domain (e.g. XrTime)
 * before delivering the measurement through the callback.
 *
 * Usage (monotonic):
 * @code
 *     auto client = ClockClient::Create("192.168.1.100", 5555,
 *         [](const ClockMeasurement& m) {
 *             std::cout << "rtt=" << m.rtt() << " offset=" << m.offset() << "\n";
 *         });
 *     client->ping();
 *     client.reset();
 * @endcode
 *
 * Usage (with translator, e.g. XrTime):
 * @code
 *     auto xr = XrClockTranslator::Create();
 *     auto client = ClockClient::Create("192.168.1.100", 5555,
 *         my_callback, xr->make_translator());
 * @endcode
 */
class ClockClient
{
public:
    using MeasurementCallback = std::function<void(const ClockMeasurement&)>;

    /*!
     * @brief Factory method.
     * @param server_ip   IPv4 address of the clock server.
     * @param port        UDP port (default kDefaultClockPort).
     * @param callback    Called from the receiver thread for every reply.
     * @param translator  Optional translator applied to client-side timestamps
     *                    (t1, t4) before delivering the measurement.  Pass
     *                    nullptr for raw CLOCK_MONOTONIC nanoseconds.
     * @return A shared_ptr to the new client. The receiver thread is already running.
     * @throws std::runtime_error if the socket cannot be created or the address is invalid.
     */
    static std::shared_ptr<ClockClient> Create(const std::string& server_ip,
                                               uint16_t port = kDefaultClockPort,
                                               MeasurementCallback callback = nullptr,
                                               ClockTranslator translator = nullptr);

    ~ClockClient();

    ClockClient(const ClockClient&) = delete;
    ClockClient& operator=(const ClockClient&) = delete;

    /// Replace the measurement callback.  Thread-safe.
    void set_callback(MeasurementCallback cb);

    /*!
     * @brief Send a single clock request (non-blocking).
     *
     * The result will be delivered asynchronously through the callback when
     * (and if) the server replies.  Lost packets simply produce no callback.
     */
    void ping();

    /*!
     * @brief Start periodic pinging on a background thread.
     * @param interval_ms Milliseconds between consecutive pings.
     * @param count       Number of pings (0 = unlimited until `stop()`).
     * @throws std::runtime_error if periodic pinging is already active.
     */
    void start(int interval_ms, int count = 0);

    /*!
     * @brief Stop periodic pinging.  The receiver thread keeps running.
     *
     * Safe to call even if not running (no-op).
     */
    void stop();

    /// @return true while the periodic sender thread is active.
    bool is_running() const
    {
        return sending_.load(std::memory_order_relaxed);
    }

private:
    ClockClient() = default;
    void initialize(const std::string& server_ip, uint16_t port);
    void receiver_loop();
    void sender_loop(int interval_ms, int count);

    socket_t sock_{ kInvalidSocket };
    ::sockaddr_in server_addr_{};

    ClockTranslator translator_;

    // Receiver thread — lives for the entire lifetime of the object
    std::atomic<bool> alive_{ false };
    std::thread receiver_;

    // Optional periodic sender thread
    std::atomic<bool> sending_{ false };
    std::thread sender_;

    std::mutex callback_mutex_;
    MeasurementCallback callback_;
};

} // namespace core
