// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>

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
//! The device exposes the packet geometry here so the host never hardcodes
//! sizes. Only the fields the plugin consumes at runtime are kept.
struct OgloDeviceConfig
{
    int schema_ver = 0;
    std::string packet_format; //!< e.g. "packed12_v5"
    int values_per_sample = 80; //!< taxel count per sample
    int rate_hz = 0; //!< nominal sample rate
    Side side = Side::Unknown; //!< left / right
    std::string serial; //!< device serial (logged on connect)

    //! Parse a Config-characteristic JSON payload. Missing fields keep their
    //! defaults; malformed JSON throws std::runtime_error.
    static OgloDeviceConfig parse(const std::string& json);
};

} // namespace oglo_tactile
} // namespace plugins
