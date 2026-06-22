// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#define MCAP_IMPLEMENTATION
#include "oglo_glove_sink.hpp"

#include <flatbuffers/flatbuffers.h>
#include <mcap/writer.hpp>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/oglo_tactile_bfbs_generated.h>
#include <schema/oglo_tactile_generated.h>

#include <iostream>
#include <stdexcept>

namespace plugins
{
namespace oglo_tactile
{

namespace
{

// 80 taxels * 2B + 6 IMU * 2B + table overhead. 512 is comfortable headroom.
constexpr size_t kMaxFlatbufferSize = 512;

//! Serialize a GloveSample into the schema's native packing type.
core::OgloGloveSampleT to_native(const GloveSample& s)
{
    core::OgloGloveSampleT out;
    out.seq = s.seq;
    out.device_time_us = s.device_time_us;
    out.taxels.assign(s.taxels.begin(), s.taxels.end());
    out.accel_x = s.imu.ax;
    out.accel_y = s.imu.ay;
    out.accel_z = s.imu.az;
    out.gyro_x = s.imu.gx;
    out.gyro_y = s.imu.gy;
    out.gyro_z = s.imu.gz;
    return out;
}

// =============================================================================
// Mode 1: local MCAP file (self-contained; no OpenXR / TeleopSession)
// =============================================================================

class McapGloveSink final : public IGloveSink
{
public:
    McapGloveSink(Side side, const OgloDeviceConfig& config, const std::string& mcap_filename)
    {
        mcap::McapWriterOptions options("oglo_tactile");
        options.compression = mcap::Compression::None;

        auto status = m_writer.open(mcap_filename, options);
        if (!status.ok())
            throw std::runtime_error("OGLO MCAP: failed to open " + mcap_filename + ": " + status.message);

        mcap::Schema schema("core.OgloGloveSampleRecord", "flatbuffer",
                            std::string(reinterpret_cast<const char*>(core::OgloGloveSampleRecordBinarySchema::data()),
                                        core::OgloGloveSampleRecordBinarySchema::size()));
        m_writer.addSchema(schema);

        const std::string channel_name = std::string("oglo_") + to_string(side);
        mcap::Channel channel(channel_name, "flatbuffer", schema.id);
        m_writer.addChannel(channel);
        m_channel_id = channel.id;

        write_device_metadata(side, config);

        std::cout << "MCAP recording '" << channel_name << "' to: " << mcap_filename << std::endl;
    }

    ~McapGloveSink() override
    {
        m_writer.close();
        std::cout << "MCAP closed with " << m_message_count << " messages" << std::endl;
    }

    void on_sample(const GloveSample& sample, int64_t local_ns, int64_t raw_ns) override
    {
        const int64_t now_ns = core::os_monotonic_now_ns();

        flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
        auto native = to_native(sample);
        auto data_offset = core::OgloGloveSample::Pack(builder, &native);
        core::DeviceDataTimestamp timestamp(now_ns, local_ns, raw_ns);
        core::OgloGloveSampleRecordBuilder record(builder);
        record.add_data(data_offset);
        record.add_timestamp(&timestamp);
        builder.Finish(record.Finish());

        mcap::Message msg;
        msg.channelId = m_channel_id;
        msg.logTime = static_cast<mcap::Timestamp>(now_ns);
        msg.publishTime = static_cast<mcap::Timestamp>(local_ns);
        msg.sequence = sample.seq;
        msg.data = reinterpret_cast<const std::byte*>(builder.GetBufferPointer());
        msg.dataSize = builder.GetSize();

        auto status = m_writer.write(msg);
        if (!status.ok())
            std::cerr << "OGLO MCAP: write failed: " << status.message << std::endl;
        ++m_message_count;
    }

private:
    //! Attach the device Config + geometry so the dataset is self-describing.
    void write_device_metadata(Side side, const OgloDeviceConfig& config)
    {
        mcap::Metadata meta;
        meta.name = std::string("oglo_device_") + to_string(side);
        meta.metadata["side"] = to_string(side);
        meta.metadata["schema_ver"] = std::to_string(config.schema_ver);
        meta.metadata["packet_format"] = config.packet_format;
        meta.metadata["rate_hz"] = std::to_string(config.rate_hz);
        meta.metadata["values_per_sample"] = std::to_string(config.values_per_sample);
        meta.metadata["sample_order"] = config.sample_order;
        meta.metadata["serial"] = config.serial;
        meta.metadata["fw_rev"] = config.fw_rev;
        meta.metadata["device_id"] = config.device_id;
        std::string channels;
        for (size_t i = 0; i < config.channels.size(); ++i)
            channels += (i ? "," : "") + config.channels[i];
        meta.metadata["channels"] = channels;
        meta.metadata["config_json"] = config.raw_json;

        auto status = m_writer.write(meta);
        if (!status.ok())
            std::cerr << "OGLO MCAP: metadata write failed: " << status.message << std::endl;
    }

    mcap::McapWriter m_writer;
    mcap::ChannelId m_channel_id = 0;
    uint64_t m_message_count = 0;
};

// =============================================================================
// Mode 2: OpenXR SchemaPusher (read by a host tracker into a shared MCAP)
// =============================================================================

class SchemaPusherGloveSink final : public IGloveSink
{
public:
    SchemaPusherGloveSink(Side side, const std::string& collection_prefix)
        : m_session(std::make_shared<core::OpenXRSession>(
              "OgloTactilePlugin", core::SchemaPusher::get_required_extensions())),
          m_pusher(m_session->get_handles(),
                   core::SchemaPusherConfig{ .collection_id = collection_prefix + "/" + to_string(side),
                                             .max_flatbuffer_size = kMaxFlatbufferSize,
                                             .tensor_identifier = "oglo_tactile",
                                             .localized_name = "OGLO Tactile Glove",
                                             .app_name = "OgloTactilePlugin" })
    {
        std::cout << "Pushing collection: " << collection_prefix << "/" << to_string(side) << std::endl;
    }

    void on_sample(const GloveSample& sample, int64_t local_ns, int64_t raw_ns) override
    {
        flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
        auto native = to_native(sample);
        auto offset = core::OgloGloveSample::Pack(builder, &native);
        builder.Finish(offset);
        m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize(), local_ns, raw_ns);
    }

private:
    std::shared_ptr<core::OpenXRSession> m_session;
    core::SchemaPusher m_pusher;
};

} // namespace

std::unique_ptr<IGloveSink> create_glove_sink(Side side,
                                              const OgloDeviceConfig& config,
                                              const std::string& mcap_filename,
                                              const std::string& collection_prefix)
{
    if (!mcap_filename.empty() && !collection_prefix.empty())
        throw std::runtime_error("Specify only one of --mcap-filename or --collection-prefix");
    if (mcap_filename.empty() && collection_prefix.empty())
        throw std::runtime_error("One of --mcap-filename or --collection-prefix is required");

    if (!mcap_filename.empty())
        return std::make_unique<McapGloveSink>(side, config, mcap_filename);
    return std::make_unique<SchemaPusherGloveSink>(side, collection_prefix);
}

} // namespace oglo_tactile
} // namespace plugins
