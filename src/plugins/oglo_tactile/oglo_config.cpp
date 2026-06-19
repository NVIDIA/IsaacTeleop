// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oglo_config.hpp"

#include <nlohmann/json.hpp>

#include <stdexcept>

namespace plugins
{
namespace oglo_tactile
{

const char* to_string(Side side) noexcept
{
    switch (side)
    {
    case Side::Left:
        return "left";
    case Side::Right:
        return "right";
    case Side::Unknown:
    default:
        return "unknown";
    }
}

Side side_from_string(const std::string& s) noexcept
{
    if (s == "left")
        return Side::Left;
    if (s == "right")
        return Side::Right;
    return Side::Unknown;
}

namespace
{

// Tolerant getters: the Config schema evolves across firmware revisions, so a
// missing or wrong-typed field falls back to the default rather than throwing.
template <typename T>
T get_or(const nlohmann::json& j, const char* key, T fallback)
{
    auto it = j.find(key);
    if (it == j.end() || it->is_null())
        return fallback;
    try
    {
        return it->get<T>();
    }
    catch (const nlohmann::json::exception&)
    {
        return fallback;
    }
}

} // namespace

OgloDeviceConfig OgloDeviceConfig::parse(const std::string& json)
{
    nlohmann::json j = nlohmann::json::parse(json); // throws on malformed JSON

    OgloDeviceConfig cfg;
    cfg.raw_json = json;
    cfg.schema_ver = get_or<int>(j, "schema_ver", 0);
    cfg.packet_format = get_or<std::string>(j, "packet_format", "");
    cfg.values_per_sample = get_or<int>(j, "values_per_sample", 80);
    cfg.samples_per_packet = get_or<int>(j, "samples_per_packet", 0);
    cfg.rate_hz = get_or<int>(j, "rate_hz", 0);
    cfg.sample_order = get_or<std::string>(j, "sample_order", "");
    cfg.sample_shape = get_or<std::vector<int>>(j, "sample_shape", {});
    cfg.channels = get_or<std::vector<std::string>>(j, "channels", {});
    cfg.side = side_from_string(get_or<std::string>(j, "side", ""));
    cfg.serial = get_or<std::string>(j, "serial", "");
    cfg.fw_rev = get_or<std::string>(j, "fw_rev", "");
    cfg.device_id = get_or<std::string>(j, "device_id", "");

    if (cfg.values_per_sample <= 0)
        throw std::runtime_error("OGLO Config: invalid values_per_sample");

    return cfg;
}

} // namespace oglo_tactile
} // namespace plugins
