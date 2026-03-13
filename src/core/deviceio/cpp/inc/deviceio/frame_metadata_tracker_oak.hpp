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
    static constexpr const char* TRACKER_NAME = "FrameMetadataTrackerOak";
    static constexpr const char* SCHEMA_NAME = "core.FrameMetadataOakRecord";

    std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
    std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const override;

    std::vector<SchemaTrackerConfig> m_configs;
    std::vector<std::string> m_channel_names;

    struct IImpl
    {
        virtual ~IImpl() = default;
        virtual const FrameMetadataOakTrackedT& get_stream_data(size_t stream_index) const = 0;
    };

    class Impl : public ILiveTrackerImpl, public IImpl
    {
    public:
        Impl(const OpenXRSessionHandles& handles,
             std::vector<SchemaTrackerConfig> configs,
             std::vector<std::string> record_channels);

        bool update_live(int64_t system_monotonic_time_ns) override;
        void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

        const FrameMetadataOakTrackedT& get_stream_data(size_t stream_index) const override;

    private:
        std::vector<std::string> m_record_channels_;
        struct StreamState
        {
            std::unique_ptr<SchemaTracker> reader;
            FrameMetadataOakTrackedT tracked;
            bool collection_present = false;
            std::vector<SchemaTracker::SampleResult> pending_records;
        };

        XrTimeConverter m_time_converter_;
        int64_t m_last_update_time_ns_ = 0; // monotonic ns; XrTime only when needed
        std::vector<StreamState> m_streams;
    };

    class ReplayImpl : public IReplayTrackerImpl, public IImpl
    {
    public:
        ReplayImpl(const ITrackerSession& session, size_t stream_count);

        bool update_replay(int64_t replay_time_ns) override;

        const FrameMetadataOakTrackedT& get_stream_data(size_t stream_index) const override;

    private:
        const ITrackerSession* session_;
        std::vector<FrameMetadataOakTrackedT> stream_tracked_;
    };
};

} // namespace core
