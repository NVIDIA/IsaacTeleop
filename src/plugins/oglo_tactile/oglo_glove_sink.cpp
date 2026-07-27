// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oglo_glove_sink.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
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
// OpenXR SchemaPusher sink (read by a host tracker into a shared session MCAP)
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

std::unique_ptr<IGloveSink> create_glove_sink(Side side, const std::string& collection_prefix)
{
    if (collection_prefix.empty())
        throw std::runtime_error("OGLO: --collection-prefix is required");

    return std::make_unique<SchemaPusherGloveSink>(side, collection_prefix);
}

} // namespace oglo_tactile
} // namespace plugins
