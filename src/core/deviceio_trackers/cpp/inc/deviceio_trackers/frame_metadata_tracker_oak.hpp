// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/frame_metadata_tracker_oak_base.hpp>
#include <schema/oak_generated.h>

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace core
{

/*!
 * @brief Multi-stream tracker for OAK FrameMetadataOak.
 *
 * Maintains one SchemaTracker per stream. Each stream is identified by its
 * StreamType enum name (e.g., "Color", "MonoLeft").
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<FrameMetadataTrackerOak>(
 *     "oak_camera", {StreamType_Color, StreamType_MonoLeft});
 * // ... create session with tracker ...
 * session->update(core::os_monotonic_now_ns());
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

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Double-dispatch: calls factory.create_frame_metadata_tracker_oak_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    /*!
     * @brief Get per-stream frame metadata.
     * @param session Active ITrackerSession.
     * @param stream_index Index into the streams vector passed at construction.
     * @return Reference to the FrameMetadataOakTrackedT for that stream.
     *         The inner @c data pointer is null until the first frame arrives.
     */
    const FrameMetadataOakTrackedT& get_stream_data(const ITrackerSession& session, size_t stream_index) const;

    //! Number of streams this tracker is configured for.
    size_t get_stream_count() const
    {
        return m_stream_names.size();
    }

    const std::string& collection_prefix() const
    {
        return collection_prefix_;
    }

    const std::vector<StreamType>& streams() const
    {
        return streams_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

    const std::vector<std::string>& get_stream_names() const
    {
        return m_stream_names;
    }

private:
    static constexpr const char* TRACKER_NAME = "FrameMetadataTrackerOak";

    std::string collection_prefix_;
    std::vector<StreamType> streams_;
    size_t max_flatbuffer_size_{ DEFAULT_MAX_FLATBUFFER_SIZE };
    std::vector<std::string> m_stream_names;
};

} // namespace core
