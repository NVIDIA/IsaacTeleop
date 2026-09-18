// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_full_body_tracker_xsens_impl.hpp"

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

SchemaTrackerConfig make_xsens_tensor_config(const TrackerVendor& vendor)
{
    if (vendor.id != LiveFullBodyTrackerXsensImpl::VENDOR_ID)
    {
        throw std::invalid_argument("Xsens full-body vendor id must be '" +
                                    std::string(LiveFullBodyTrackerXsensImpl::VENDOR_ID) + "'");
    }

    for (const auto& [key, value] : vendor.params)
    {
        (void)value;
        if (key != COLLECTION_ID_PARAM && key != MAX_FLATBUFFER_SIZE_PARAM)
        {
            throw std::invalid_argument("Xsens full-body vendor does not support parameter '" + key + "'");
        }
    }

    SchemaTrackerConfig config;
    config.collection_id = std::string(LiveFullBodyTrackerXsensImpl::DEFAULT_COLLECTION_ID);
    config.max_flatbuffer_size = LiveFullBodyTrackerXsensImpl::DEFAULT_MAX_FLATBUFFER_SIZE;
    config.tensor_identifier = std::string(LiveFullBodyTrackerXsensImpl::TENSOR_IDENTIFIER);
    config.localized_name = "Xsens Full Body";

    if (auto it = vendor.params.find(std::string(COLLECTION_ID_PARAM)); it != vendor.params.end())
    {
        // A collection_id mismatch between pusher and reader fails SILENTLY and forever -- the
        // two sides rendezvous on this string and simply never connect. An empty one is always a
        // configuration error, so reject it loudly here rather than hang later.
        if (it->second.empty())
        {
            throw std::invalid_argument("Xsens full-body collection_id must not be empty");
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
            throw std::invalid_argument("Xsens full-body max_flatbuffer_size must be a positive integer");
        }
        config.max_flatbuffer_size = parsed;
    }

    return config;
}

} // namespace

void LiveFullBodyTrackerXsensImpl::validate_vendor(const TrackerVendor& vendor)
{
    (void)make_xsens_tensor_config(vendor);
}

LiveFullBodyTrackerXsensImpl::LiveFullBodyTrackerXsensImpl(const OpenXRSessionHandles& handles,
                                                           const TrackerVendor& vendor,
                                                           std::unique_ptr<FullBodyXsensMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      schema_reader_(handles, make_xsens_tensor_config(vendor), mcap_channels_.get(), /*mcap_channel_index=*/0)
{
}

void LiveFullBodyTrackerXsensImpl::update(int64_t /*monotonic_time_ns*/)
{
    schema_reader_.update(tracked_);
}

const Serialized<FullBodyPose>& LiveFullBodyTrackerXsensImpl::get_body_pose() const
{
    return tracked_;
}

} // namespace core
