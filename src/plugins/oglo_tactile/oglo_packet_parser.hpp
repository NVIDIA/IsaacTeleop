// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace plugins
{
namespace oglo_tactile
{

// OGLO tactile matrix geometry (fixed by the OGLO sensor flex).
constexpr int kNumFingers = 5;
constexpr int kRowsPerFinger = 4;
constexpr int kColsPerFinger = 4;
constexpr int kTaxelsPerFinger = kRowsPerFinger * kColsPerFinger; // 16
constexpr int kNumTaxels = kNumFingers * kTaxelsPerFinger; // 80

//! Raw 6-axis IMU sample (device LSB units, no on-device fusion).
struct ImuSample
{
    int16_t ax = 0, ay = 0, az = 0;
    int16_t gx = 0, gy = 0, gz = 0;
};

//! One decoded tactile + IMU sample for a single glove.
//!
//! @c seq and @c device_time_us are taken from the wire when present
//! (packed12 v5). For the legacy schema-4 fallbacks the wire carries no
//! per-sample sequence/timestamp, so @c seq is the index within the packet and
//! @c device_time_us is the packet base timestamp; the plugin layer rebases
//! these against a host counter / sample rate.
struct GloveSample
{
    uint32_t seq = 0;
    uint32_t device_time_us = 0;
    std::array<uint16_t, kNumTaxels> taxels{}; // raw 12-bit ADC, [0, 4095]
    ImuSample imu{};
};

//! Wire framing, selected by the notify @c flags byte. The host MUST read the
//! Config characteristic first and never hardcode sizes; the parser branches on
//! @c flags so a firmware that switches framing (SET BLEFMT) keeps working.
enum class PacketFormat
{
    Unknown,
    Packed12V5, //!< flags bit2 (0x04): 12-bit taxels + per-sample 6-axis raw IMU.
    MethodC, //!< flags bit1 (0x02): schema-4, 16-bit taxels-only samples + one trailing IMU.
    MethodB, //!< flags bit0 (0x01): schema-4, 16-bit taxels + per-sample 17B IMU.
};

PacketFormat format_from_flags(uint8_t flags) noexcept;

//! Stateless parser for a single BLE notify payload.
//!
//! All multi-byte fields are little-endian. The parser is intentionally free of
//! any BLE / FlatBuffers dependency so it can be unit-tested against the
//! firmware reference vectors (the OGLO packed12-v5 packing reference).
class PacketParser
{
public:
    //! Parse @p data (@p len bytes) and append the decoded samples to @p out.
    //!
    //! @param values_per_sample Taxel count from the Config characteristic
    //!        (normally 80). Used to size the legacy schema-4 sample stride.
    //! @return true if the packet was well-formed and fully decoded; false if it
    //!         was truncated or had an unknown framing (in which case @p out is
    //!         left unmodified).
    static bool parse(const uint8_t* data, size_t len, int values_per_sample, std::vector<GloveSample>& out);

    //! Unpack 80 12-bit taxels from a 120-byte packed block (packed12 v5).
    //! Triplet (b0,b1,b2) -> even=(b0<<4)|(b1>>4), odd=((b1&0x0F)<<8)|b2.
    static void unpack_taxels12(const uint8_t* packed120, std::array<uint16_t, kNumTaxels>& out) noexcept;

private:
    static bool parse_packed12_v5(const uint8_t* data, size_t len, std::vector<GloveSample>& out);
    static bool parse_schema4(const uint8_t* data,
                              size_t len,
                              int values_per_sample,
                              bool per_sample_imu,
                              bool packet_imu,
                              std::vector<GloveSample>& out);
};

} // namespace oglo_tactile
} // namespace plugins
