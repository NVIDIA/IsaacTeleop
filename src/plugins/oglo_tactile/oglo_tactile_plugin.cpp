// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oglo_tactile_plugin.hpp"

#include <oxr_utils/os_time.hpp>

#include <chrono>
#include <iostream>
#include <thread>
#include <vector>

namespace plugins
{
namespace oglo_tactile
{

namespace
{
constexpr int64_t kNsPerUs = 1000;
constexpr uint64_t kDeviceUsWrap = (1ull << 32); // device_time_us is uint32
} // namespace

OgloTactilePlugin::OgloTactilePlugin(Options options) : m_opts(std::move(options))
{
    m_ble = make_ble_client(m_opts.device_name_override);
    m_ble->on_state_change([this](bool connected) { m_connected.store(connected, std::memory_order_relaxed); });
}

OgloTactilePlugin::~OgloTactilePlugin()
{
    if (m_ble)
        m_ble->disconnect();
}

int64_t OgloTactilePlugin::extend_device_ns(uint32_t device_time_us)
{
    // Promote the wrapping 32-bit microsecond counter to a monotonic 64-bit ns
    // value so recorded raw-device timestamps don't jump backwards every ~71 min.
    if (m_have_last_us && device_time_us < m_last_device_us && (m_last_device_us - device_time_us) > (kDeviceUsWrap / 2))
    {
        m_device_wrap_offset_ns += static_cast<int64_t>(kDeviceUsWrap) * kNsPerUs;
    }
    m_last_device_us = device_time_us;
    m_have_last_us = true;
    return m_device_wrap_offset_ns + static_cast<int64_t>(device_time_us) * kNsPerUs;
}

void OgloTactilePlugin::connect_and_subscribe()
{
    std::cout << "Scanning for " << advertised_name_for(m_opts.side) << "..." << std::endl;
    const std::string config_json = m_ble->connect(m_opts.side, m_opts.scan_timeout);
    m_config = OgloDeviceConfig::parse(config_json);
    m_values_per_sample.store(m_config.values_per_sample, std::memory_order_relaxed);

    // The device's microsecond clock restarts on reconnect, so reset the wrap
    // tracker; otherwise a stale m_last_device_us would spuriously trip the wrap
    // detector on the first packet of the new session. Safe to touch here: the
    // BLE notify thread is quiesced by disconnect() before we re-subscribe below.
    m_have_last_us = false;
    m_last_device_us = 0;
    m_device_wrap_offset_ns = 0;

    std::cout << "Connected: side=" << to_string(m_config.side) << " schema_ver=" << m_config.schema_ver
              << " format=" << m_config.packet_format << " rate=" << m_config.rate_hz << "Hz"
              << " serial=" << m_config.serial << std::endl;

    // The sink is created once (first connect); reconnects reuse it so the MCAP
    // file / OpenXR collection stays continuous across drops.
    if (!m_sink)
        m_sink = create_glove_sink(m_opts.side, m_config, m_opts.mcap_filename, m_opts.collection_prefix);

    m_ble->subscribe([this](const uint8_t* data, std::size_t len) { on_notify(data, len); });
    m_last_notify_ns.store(core::os_monotonic_now_ns(), std::memory_order_relaxed);
}

void OgloTactilePlugin::on_notify(const uint8_t* data, std::size_t len)
{
    // Runs on the BLE backend thread: parse + timestamp + enqueue only.
    const int64_t arrival_ns = core::os_monotonic_now_ns();
    m_last_notify_ns.store(arrival_ns, std::memory_order_relaxed);

    std::vector<GloveSample> samples;
    if (!PacketParser::parse(data, len, m_values_per_sample.load(std::memory_order_relaxed), samples) || samples.empty())
        return;

    // Anchor the newest sample of the batch to arrival time and back-date the
    // earlier samples by their intra-batch device delta (no wrap within a batch).
    const uint32_t newest_us = samples.back().device_time_us;
    for (const auto& s : samples)
    {
        const int64_t intra_batch_ns = static_cast<int64_t>(newest_us - s.device_time_us) * kNsPerUs;
        QueuedSample q;
        q.sample = s;
        q.local_ns = arrival_ns - intra_batch_ns;
        q.raw_ns = extend_device_ns(s.device_time_us);
        enqueue(q);
    }
}

void OgloTactilePlugin::enqueue(const QueuedSample& q)
{
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_queue.push_back(q);
    }
    m_cv.notify_one();
}

void OgloTactilePlugin::run(std::atomic<bool>& stop)
{
    connect_and_subscribe();

    while (!stop.load(std::memory_order_relaxed))
    {
        std::deque<QueuedSample> batch;
        {
            std::unique_lock<std::mutex> lock(m_mutex);
            m_cv.wait_for(lock, std::chrono::milliseconds(100), [&] { return !m_queue.empty(); });
            batch.swap(m_queue);
        }

        for (const auto& q : batch)
        {
            m_sink->on_sample(q.sample, q.local_ns, q.raw_ns);
            ++m_total_samples;
        }

        // Stall / disconnect watchdog: if no notifications have arrived within
        // the stall window, force a reconnect (the BLE link may have dropped
        // silently). Recording continues into the same sink.
        const int64_t now_ns = core::os_monotonic_now_ns();
        const int64_t since_notify_ms = (now_ns - m_last_notify_ns.load(std::memory_order_relaxed)) / 1'000'000;
        const bool stalled = since_notify_ms > m_opts.stall_timeout.count();
        if ((stalled || !m_connected.load(std::memory_order_relaxed)) && !stop.load(std::memory_order_relaxed))
        {
            std::cerr << "OGLO: link stalled/dropped (" << since_notify_ms << " ms), reconnecting..." << std::endl;
            try
            {
                m_ble->disconnect();
                connect_and_subscribe();
            }
            catch (const std::exception& e)
            {
                std::cerr << "OGLO: reconnect failed: " << e.what() << " — retrying." << std::endl;
                std::this_thread::sleep_for(std::chrono::milliseconds(500));
            }
        }
    }

    // Quiesce the producer, then drain anything the BLE thread queued before we
    // observed `stop`, so the tail of a recording is never silently dropped.
    m_ble->disconnect();
    std::deque<QueuedSample> tail;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        tail.swap(m_queue);
    }
    for (const auto& q : tail)
    {
        m_sink->on_sample(q.sample, q.local_ns, q.raw_ns);
        ++m_total_samples;
    }

    std::cout << "OGLO: stopped after " << m_total_samples << " samples." << std::endl;
}

} // namespace oglo_tactile
} // namespace plugins
