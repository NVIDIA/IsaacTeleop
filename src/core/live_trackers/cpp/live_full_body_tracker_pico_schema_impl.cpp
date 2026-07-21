// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_full_body_tracker_pico_schema_impl.hpp"

#include <string>
#include <utility>

namespace core
{

namespace
{

SchemaTrackerConfig make_full_body_pico_tensor_config(const FullBodyTrackerPico* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = std::string(FullBodyTrackerPico::TENSOR_IDENTIFIER);
    cfg.localized_name = "FullBodyTrackerPico";
    return cfg;
}

} // namespace

LiveFullBodyTrackerPicoSchemaImpl::LiveFullBodyTrackerPicoSchemaImpl(const OpenXRSessionHandles& handles,
                                                                     const FullBodyTrackerPico* tracker,
                                                                     std::unique_ptr<FullBodyMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles, make_full_body_pico_tensor_config(tracker), mcap_channels_.get(), /*mcap_channel_index=*/0)
{
}

void LiveFullBodyTrackerPicoSchemaImpl::update(int64_t /*monotonic_time_ns*/)
{
    m_schema_reader.update(tracked_.data);
}

const FullBodyPosePicoTrackedT& LiveFullBodyTrackerPicoSchemaImpl::get_body_pose() const
{
    return tracked_;
}

} // namespace core
