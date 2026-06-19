// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>
#include <vector>

namespace plugins
{
namespace oglo_tactile
{

//! Hand side of a glove, as reported by the device Config characteristic.
enum class Side
{
    Unknown,
    Left,
    Right,
};

const char* to_string(Side side) noexcept;
Side side_from_string(const std::string& s) noexcept;

//! Decoded contents of the OGLO Config characteristic (JSON).
//!
//! The firmware exposes the packet geometry here so the host never hardcodes
//! sizes (per the OGLO firmware packet-format spec). The raw JSON is retained so it can be
//! attached to the MCAP recording, making each dataset self-describing.
struct OgloDeviceConfig
{
    int schema_ver = 0;
    std::string packet_format; //!< e.g. "packed12_v5"
    int values_per_sample = 80; //!< taxel count per sample
    int samples_per_packet = 0; //!< samples batched per BLE notify
    int rate_hz = 0; //!< nominal sample rate
    std::string sample_order; //!< e.g. "finger,row,col"
    std::vector<int> sample_shape; //!< e.g. [5, 4, 4]
    std::vector<std::string> channels; //!< side-aware finger order (thumb..pinky)
    Side side = Side::Unknown; //!< left / right
    std::string serial;
    std::string fw_rev;
    std::string device_id;

    std::string raw_json; //!< verbatim Config payload, for MCAP metadata.

    //! Parse a Config-characteristic JSON payload. Missing fields keep their
    //! defaults; malformed JSON throws std::runtime_error.
    static OgloDeviceConfig parse(const std::string& json);
};

} // namespace oglo_tactile
} // namespace plugins
