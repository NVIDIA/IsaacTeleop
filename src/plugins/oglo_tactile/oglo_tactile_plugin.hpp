// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "ble/oglo_ble_client.hpp"
#include "oglo_config.hpp"
#include "oglo_glove_sink.hpp"
#include "oglo_packet_parser.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>

namespace plugins
{
namespace oglo_tactile
{

//! Drives one OGLO glove end to end: BLE connect -> Config -> notify parse ->
//! record / push. BLE notifications are parsed on the backend thread and queued;
//! a single consumer thread (run()) drains the queue and owns the sink so all
//! OpenXR / MCAP I/O happens on one thread.
class OgloTactilePlugin
{
public:
    struct Options
    {
        Side side = Side::Unknown;
        std::string mcap_filename; //!< Mode 1 (XOR collection_prefix)
        std::string collection_prefix; //!< Mode 2 (XOR mcap_filename)
        std::string device_name_override; //!< pin a specific advertised name
        std::chrono::milliseconds scan_timeout{ 15000 };
        std::chrono::milliseconds stall_timeout{ 3000 }; //!< no-notify -> reconnect
    };

    explicit OgloTactilePlugin(Options options);
    ~OgloTactilePlugin();

    //! Connect, then run until @p stop is set. Reconnects automatically on drop.
    void run(std::atomic<bool>& stop);

private:
    struct QueuedSample
    {
        GloveSample sample;
        int64_t local_ns;
        int64_t raw_ns;
    };

    void connect_and_subscribe();
    void on_notify(const uint8_t* data, std::size_t len); // BLE thread
    void enqueue(const QueuedSample& q);

    //! Extend the device's 32-bit microsecond clock to a wrap-free 64-bit ns.
    int64_t extend_device_ns(uint32_t device_time_us);

    Options m_opts;
    OgloDeviceConfig m_config;
    // Written by the consumer thread on (re)connect, read by the BLE thread in
    // on_notify(); atomic so the geometry handoff across threads is race-free.
    std::atomic<int> m_values_per_sample{ kNumTaxels };

    std::unique_ptr<OgloBleClient> m_ble;
    std::unique_ptr<IGloveSink> m_sink;

    // BLE-thread -> consumer-thread sample queue.
    std::mutex m_mutex;
    std::condition_variable m_cv;
    std::deque<QueuedSample> m_queue;

    std::atomic<int64_t> m_last_notify_ns{ 0 };
    std::atomic<bool> m_connected{ false };

    // Device-clock extension state (consumer side: only touched on BLE thread).
    bool m_have_last_us = false;
    uint32_t m_last_device_us = 0;
    int64_t m_device_wrap_offset_ns = 0;

    uint64_t m_total_samples = 0;
};

} // namespace oglo_tactile
} // namespace plugins
