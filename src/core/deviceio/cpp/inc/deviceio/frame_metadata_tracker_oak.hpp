// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_tracker.hpp"
#include "tracker.hpp"

#include <schema/oak_generated.h>

#include <memory>
#include <string>
#include <vector>

namespace core
{

/*!
 * @brief Multi-channel tracker for reading OAK FrameMetadataOak from multiple streams.
 *
 * Maintains one SchemaTracker per stream and records each as a separate MCAP
 * channel using FrameMetadataOak as the root type.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<FrameMetadataTrackerOak>(
 *     "oak_camera", {StreamType_Color, StreamType_MonoLeft});
 * // ... create DeviceIOSession with tracker ...
 * session->update();
 * const auto& color = tracker->get_stream_data(*session, 0);
 * if (color.data)
 *     std::cout << EnumNameStreamType(color.data->stream) << " seq=" << color.data->sequence_number << std::endl;
 * @endcode
 */
class FrameMetadataTrackerOak : public ITracker
{
public:
    //! Default maximum FlatBuffer size for individual FrameMetadataOak messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 128;

    /*!
     * @brief Constructs a multi-stream FrameMetadataOak tracker.
     * @param collection_prefix Base prefix for per-stream collection IDs.
     *        Each stream gets collection_id = "{collection_prefix}/{StreamName}".
     * @param streams Stream types to track.
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size per stream (default: 128 bytes).
     */
    FrameMetadataTrackerOak(const std::string& collection_prefix,
                            const std::vector<StreamType>& streams,
                            size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override;
    std::string_view get_schema_name() const override;
    std::string_view get_schema_text() const override;

    std::vector<std::string> get_record_channels() const override
    {
        return m_channel_names;
    }

    /*!
     * @brief Get per-stream frame metadata.
     * @param session Active DeviceIOSession.
     * @param stream_index Index into the streams vector passed at construction.
     * @return Reference to the FrameMetadataOakTrackedT for that stream.
     *         The inner @c data pointer is null until the first frame arrives.
     */
    const FrameMetadataOakTrackedT& get_stream_data(const DeviceIOSession& session, size_t stream_index) const;

    //! Number of streams this tracker is configured for.
    size_t get_stream_count() const
    {
        return m_channel_names.size();
    }

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    std::vector<SchemaTrackerConfig> m_configs;
    std::vector<std::string> m_channel_names;
    class Impl;
};

} // namespace core
