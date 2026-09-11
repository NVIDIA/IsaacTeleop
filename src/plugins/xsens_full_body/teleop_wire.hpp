// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The "XTLP" wire format MVN Studio emits on its Isaac Teleop network-streamer preset.
//
// One frame per UDP datagram: a fixed 36-byte little-endian header followed by `payload_len`
// bytes of a bare `core::FullBodyPose` FlatBuffer. Mirrors MVN's own authority,
// bsn_stack/mvn/mvn_studio/src/picofullbody_core/teleop_wire.h.
//
//   offset size field
//   0      4    magic = "XTLP"
//   4      2    version = 1
//   6      2    reserved  -- v1 receivers MUST ignore; any future use needs a version bump
//   8      8    seq (uint64)
//   16     8    sample_time_ns (int64), MVN's send-host clock -- a DIFFERENT clock domain
//   24     8    raw_device_time_ns (int64), MVN's device clock
//   32     4    payload_len (uint32)
//
// Deliberately hand-decoded field by field rather than memcpy'd into a packed struct: the wire
// is little-endian regardless of host, and a struct would silently disagree on a big-endian
// build. Framing only -- this says nothing about whether the payload is a valid FlatBuffer,
// which is why the plugin runs a flatbuffers::Verifier before pushing anything.

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <optional>

namespace plugins
{
namespace xsens_full_body
{

constexpr uint32_t TELEOP_WIRE_MAGIC = 0x504C5458u; // 'X','T','L','P' little-endian
constexpr uint16_t TELEOP_WIRE_VERSION = 1;
constexpr size_t TELEOP_WIRE_HEADER_SIZE = 36;

struct TeleopFrame
{
    uint64_t seq = 0;
    int64_t sample_time_ns = 0;
    int64_t raw_device_time_ns = 0;
    const uint8_t* payload = nullptr;
    size_t payload_size = 0;
};

namespace detail
{

inline uint16_t read_u16_le(const uint8_t* p)
{
    return static_cast<uint16_t>(p[0]) | static_cast<uint16_t>(static_cast<uint16_t>(p[1]) << 8);
}

inline uint32_t read_u32_le(const uint8_t* p)
{
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) | (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

inline uint64_t read_u64_le(const uint8_t* p)
{
    uint64_t value = 0;
    for (int i = 7; i >= 0; --i)
    {
        value = (value << 8) | static_cast<uint64_t>(p[static_cast<size_t>(i)]);
    }
    return value;
}

} // namespace detail

/*!
 * @brief Decode the XTLP header and locate the payload inside `data`.
 *
 * @return The frame, or nullopt when the datagram is not a well-formed XTLP v1 frame. The
 *         returned `payload` points into `data` and does not outlive it.
 */
inline std::optional<TeleopFrame> deserialize_teleop_frame(const uint8_t* data, size_t size)
{
    if (data == nullptr || size < TELEOP_WIRE_HEADER_SIZE)
    {
        return std::nullopt;
    }
    if (detail::read_u32_le(data) != TELEOP_WIRE_MAGIC)
    {
        return std::nullopt;
    }
    if (detail::read_u16_le(data + 4) != TELEOP_WIRE_VERSION)
    {
        return std::nullopt;
    }
    // bytes [6:8] are `reserved` and are deliberately not read.

    const uint32_t payload_len = detail::read_u32_le(data + 32);
    if (TELEOP_WIRE_HEADER_SIZE + static_cast<size_t>(payload_len) > size)
    {
        return std::nullopt;
    }

    TeleopFrame frame;
    frame.seq = detail::read_u64_le(data + 8);
    frame.sample_time_ns = static_cast<int64_t>(detail::read_u64_le(data + 16));
    frame.raw_device_time_ns = static_cast<int64_t>(detail::read_u64_le(data + 24));
    frame.payload = data + TELEOP_WIRE_HEADER_SIZE;
    frame.payload_size = payload_len;
    return frame;
}

//! FNV-1a over the payload, for cross-checking a frame against another receiver bit for bit.
inline uint64_t fnv1a64(const uint8_t* data, size_t size)
{
    uint64_t hash = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < size; ++i)
    {
        hash ^= static_cast<uint64_t>(data[i]);
        hash *= 0x100000001b3ull;
    }
    return hash;
}

} // namespace xsens_full_body
} // namespace plugins
