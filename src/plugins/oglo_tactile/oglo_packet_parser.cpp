// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oglo_packet_parser.hpp"

namespace plugins
{
namespace oglo_tactile
{

namespace
{

// Little-endian readers (no alignment assumptions on the BLE payload).
inline uint16_t rd_u16(const uint8_t* p) noexcept
{
    return static_cast<uint16_t>(p[0]) | static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}

inline int16_t rd_i16(const uint8_t* p) noexcept
{
    return static_cast<int16_t>(rd_u16(p));
}

inline uint32_t rd_u32(const uint8_t* p) noexcept
{
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) | (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

// Wire-format constants (see the OGLO firmware packed12-v5 packet specification).
constexpr uint8_t kFlagMethodB = 0x01; // schema 4, per-sample IMU
constexpr uint8_t kFlagMethodC = 0x02; // schema 4, one packet-level IMU
constexpr uint8_t kFlagPacked12 = 0x04; // schema 5, packed 12-bit + per-sample IMU

// packed12 v5 layout.
constexpr size_t kV5HeaderBytes = 10; // count, flags, seq_base(u32), t_base_us(u32)
constexpr size_t kV5TaxelBytes = 120; // 80 x 12-bit
constexpr size_t kV5ImuBytes = 12; // 6 x i16
constexpr size_t kV5SampleStride = 2 + kV5TaxelBytes + kV5ImuBytes; // dt_us(u16) + taxels + imu = 134

// schema-4 (Method B/C) layout.
constexpr size_t kS4HeaderBytes = 6; // count, flags, base_ts_us(u32)
constexpr size_t kS4ImuBytes = 17; // roll,pitch,ax,ay,az,gx,gy,gz (8 x i16) + ok(u8)

} // namespace

PacketFormat format_from_flags(uint8_t flags) noexcept
{
    if ((flags & kFlagPacked12) != 0)
        return PacketFormat::Packed12V5;
    if ((flags & kFlagMethodC) != 0)
        return PacketFormat::MethodC;
    if ((flags & kFlagMethodB) != 0)
        return PacketFormat::MethodB;
    return PacketFormat::Unknown;
}

void PacketParser::unpack_taxels12(const uint8_t* packed120, std::array<uint16_t, kNumTaxels>& out) noexcept
{
    // 80 taxels packed as 40 triplets (2 taxels per 3 bytes).
    for (int k = 0; k < kNumTaxels / 2; ++k)
    {
        const uint8_t b0 = packed120[3 * k + 0];
        const uint8_t b1 = packed120[3 * k + 1];
        const uint8_t b2 = packed120[3 * k + 2];
        out[2 * k + 0] = static_cast<uint16_t>((static_cast<uint16_t>(b0) << 4) | (b1 >> 4));
        out[2 * k + 1] = static_cast<uint16_t>((static_cast<uint16_t>(b1 & 0x0F) << 8) | b2);
    }
}

bool PacketParser::parse_packed12_v5(const uint8_t* data, size_t len, std::vector<GloveSample>& out)
{
    if (len < kV5HeaderBytes)
        return false;

    const uint8_t count = data[0];
    const uint32_t seq_base = rd_u32(data + 2);
    const uint32_t t_base_us = rd_u32(data + 6);

    if (len < kV5HeaderBytes + static_cast<size_t>(count) * kV5SampleStride)
        return false;

    const size_t start = out.size();
    out.reserve(start + count);
    for (uint8_t i = 0; i < count; ++i)
    {
        const uint8_t* slot = data + kV5HeaderBytes + static_cast<size_t>(i) * kV5SampleStride;
        GloveSample s;
        s.seq = seq_base + i;
        s.device_time_us = t_base_us + rd_u16(slot); // dt_us
        unpack_taxels12(slot + 2, s.taxels);

        const uint8_t* imu = slot + 2 + kV5TaxelBytes;
        s.imu.ax = rd_i16(imu + 0);
        s.imu.ay = rd_i16(imu + 2);
        s.imu.az = rd_i16(imu + 4);
        s.imu.gx = rd_i16(imu + 6);
        s.imu.gy = rd_i16(imu + 8);
        s.imu.gz = rd_i16(imu + 10);
        out.push_back(s);
    }
    return true;
}

bool PacketParser::parse_schema4(const uint8_t* data,
                                 size_t len,
                                 int values_per_sample,
                                 bool per_sample_imu,
                                 bool packet_imu,
                                 std::vector<GloveSample>& out)
{
    if (len < kS4HeaderBytes || values_per_sample <= 0)
        return false;

    const uint8_t count = data[0];
    const uint32_t base_ts_us = rd_u32(data + 2);

    const size_t taxel_bytes = static_cast<size_t>(values_per_sample) * 2;
    const size_t imu_len = per_sample_imu ? kS4ImuBytes : 0;
    const size_t stride = taxel_bytes + imu_len;

    // Taxels must be fully present; a trailing Method-C IMU is best-effort.
    if (len < kS4HeaderBytes + static_cast<size_t>(count) * stride)
        return false;

    const int n_taxels = values_per_sample < kNumTaxels ? values_per_sample : kNumTaxels;

    const size_t start = out.size();
    out.reserve(start + count);
    for (uint8_t i = 0; i < count; ++i)
    {
        const uint8_t* base = data + kS4HeaderBytes + static_cast<size_t>(i) * stride;
        GloveSample s;
        s.seq = i; // schema 4 carries no per-sample sequence; plugin rebases.
        s.device_time_us = base_ts_us;
        for (int t = 0; t < n_taxels; ++t)
            s.taxels[static_cast<size_t>(t)] = rd_u16(base + static_cast<size_t>(t) * 2);

        // Method B: per-sample 17B IMU block is roll,pitch,ax,ay,az,gx,gy,gz,ok.
        // Our schema keeps only the raw 6-axis values (offsets 4..15).
        if (per_sample_imu)
        {
            const uint8_t* imu = base + taxel_bytes;
            s.imu.ax = rd_i16(imu + 4);
            s.imu.ay = rd_i16(imu + 6);
            s.imu.az = rd_i16(imu + 8);
            s.imu.gx = rd_i16(imu + 10);
            s.imu.gy = rd_i16(imu + 12);
            s.imu.gz = rd_i16(imu + 14);
        }
        out.push_back(s);
    }

    // Method C: one packet-level IMU after all taxel samples; apply to every
    // sample in this packet (best-effort, only if the bytes are present).
    if (packet_imu)
    {
        const size_t imu_off = kS4HeaderBytes + static_cast<size_t>(count) * stride;
        if (len >= imu_off + kS4ImuBytes)
        {
            const uint8_t* imu = data + imu_off;
            ImuSample shared;
            shared.ax = rd_i16(imu + 4);
            shared.ay = rd_i16(imu + 6);
            shared.az = rd_i16(imu + 8);
            shared.gx = rd_i16(imu + 10);
            shared.gy = rd_i16(imu + 12);
            shared.gz = rd_i16(imu + 14);
            for (size_t j = start; j < out.size(); ++j)
                out[j].imu = shared;
        }
    }
    return true;
}

bool PacketParser::parse(const uint8_t* data, size_t len, int values_per_sample, std::vector<GloveSample>& out)
{
    if (data == nullptr || len < 2)
        return false;

    switch (format_from_flags(data[1]))
    {
    case PacketFormat::Packed12V5:
        return parse_packed12_v5(data, len, out);
    case PacketFormat::MethodC:
        return parse_schema4(data, len, values_per_sample, /*per_sample_imu=*/false, /*packet_imu=*/true, out);
    case PacketFormat::MethodB:
        return parse_schema4(data, len, values_per_sample, /*per_sample_imu=*/true, /*packet_imu=*/false, out);
    case PacketFormat::Unknown:
    default:
        return false;
    }
}

} // namespace oglo_tactile
} // namespace plugins
