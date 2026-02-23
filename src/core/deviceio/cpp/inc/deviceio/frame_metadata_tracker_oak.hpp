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
 * @brief Composite tracker for reading OAK FrameMetadataOak from multiple streams.
 *
 * Maintains one SchemaTracker per stream and composes them into a single
 * CameraMetadataOak message for serialization / MCAP recording.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<FrameMetadataTrackerOak>(
 *     "oak_camera", {StreamType_Color, StreamType_MonoLeft});
 * // ... create DeviceIOSession with tracker ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * for (const auto& md : data.streams)
 *     std::cout << EnumNameStreamType(md->stream) << std::endl;
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
        return { "frame_metadata" };
    }

    /*!
     * @brief Get the composed OAK metadata containing all tracked streams.
     */
    const CameraMetadataOakT& get_data(const DeviceIOSession& session) const;

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    std::vector<SchemaTrackerConfig> m_configs;
    class Impl;
};

} // namespace core
