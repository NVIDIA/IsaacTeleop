// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_full_body_tracker_noitom_impl.hpp"

#include <charconv>
#include <stdexcept>
#include <string>
#include <system_error>
#include <utility>

namespace core
{

namespace
{

constexpr std::string_view COLLECTION_ID_PARAM = "collection_id";
constexpr std::string_view MAX_FLATBUFFER_SIZE_PARAM = "max_flatbuffer_size";

SchemaTrackerConfig make_noitom_tensor_config(const TrackerVendor& vendor)
{
    if (vendor.id != LiveFullBodyTrackerNoitomImpl::VENDOR_ID)
    {
        throw std::invalid_argument("Noitom full-body vendor id must be '" +
                                    std::string(LiveFullBodyTrackerNoitomImpl::VENDOR_ID) + "'");
    }

    for (const auto& [key, value] : vendor.params)
    {
        (void)value;
        if (key != COLLECTION_ID_PARAM && key != MAX_FLATBUFFER_SIZE_PARAM)
        {
            throw std::invalid_argument("Noitom full-body vendor does not support parameter '" + key + "'");
        }
    }

    SchemaTrackerConfig config;
    config.collection_id = std::string(LiveFullBodyTrackerNoitomImpl::DEFAULT_COLLECTION_ID);
    config.max_flatbuffer_size = LiveFullBodyTrackerNoitomImpl::DEFAULT_MAX_FLATBUFFER_SIZE;
    config.tensor_identifier = std::string(LiveFullBodyTrackerNoitomImpl::TENSOR_IDENTIFIER);
    config.localized_name = "Noitom Full Body";

    if (auto it = vendor.params.find(std::string(COLLECTION_ID_PARAM)); it != vendor.params.end())
    {
        if (it->second.empty())
        {
            throw std::invalid_argument("Noitom full-body collection_id must not be empty");
        }
        config.collection_id = it->second;
    }

    if (auto it = vendor.params.find(std::string(MAX_FLATBUFFER_SIZE_PARAM)); it != vendor.params.end())
    {
        size_t parsed = 0;
        const char* begin = it->second.data();
        const char* end = begin + it->second.size();
        const auto [ptr, error] = std::from_chars(begin, end, parsed);
        if (error != std::errc{} || ptr != end || parsed == 0)
        {
            throw std::invalid_argument("Noitom full-body max_flatbuffer_size must be a positive integer");
        }
        config.max_flatbuffer_size = parsed;
    }

    return config;
}

} // namespace

void LiveFullBodyTrackerNoitomImpl::validate_vendor(const TrackerVendor& vendor)
{
    (void)make_noitom_tensor_config(vendor);
}

LiveFullBodyTrackerNoitomImpl::LiveFullBodyTrackerNoitomImpl(const OpenXRSessionHandles& handles,
                                                             const TrackerVendor& vendor,
                                                             std::unique_ptr<FullBodyMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      schema_reader_(handles, make_noitom_tensor_config(vendor), mcap_channels_.get(), /*mcap_channel_index=*/0)
{
}

void LiveFullBodyTrackerNoitomImpl::update(int64_t /*monotonic_time_ns*/)
{
    schema_reader_.update(tracked_.data);
}

const FullBodyPoseTrackedT& LiveFullBodyTrackerNoitomImpl::get_body_pose() const
{
    return tracked_;
}

} // namespace core
