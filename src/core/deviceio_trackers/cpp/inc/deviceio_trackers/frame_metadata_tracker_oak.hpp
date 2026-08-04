// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/frame_metadata_tracker_oak_base.hpp>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Single-stream tracker for OAK FrameMetadataOak.
 *
 * Identified by a single collection_id (e.g., "oak_camera/Color").
 * To track multiple streams, create one tracker instance per stream.
 *
 * Usage:
 * @code
 * auto color_tracker = std::make_shared<FrameMetadataTrackerOak>("oak_camera/Color");
 * auto mono_tracker  = std::make_shared<FrameMetadataTrackerOak>("oak_camera/MonoLeft");
 * // ... create session with both trackers ...
 * session->update();
 * const auto& color = color_tracker->get_data(*session);
 * if (color.data)
 *     std::cout << color.data->sequence_number << std::endl;
 * @endcode
 */
class FrameMetadataTrackerOak : public ITracker
{
public:
    //! Default maximum FlatBuffer size for FrameMetadataOak messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 128;

    /*!
     * @brief Constructs a FrameMetadataTrackerOak.
     * @param collection_id Logical stream identifier matching the data source (e.g., "oak_camera/Color").
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size (default: 128 bytes).
     */
    explicit FrameMetadataTrackerOak(const std::string& collection_id,
                                     size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Get frame metadata for the tracked stream.
     * @param session Active ITrackerSession.
     * @return Reference to the FrameMetadataOakTrackedT.
     *         The inner @c data pointer is null until the first frame arrives.
     */
    const FrameMetadataOakTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "FrameMetadataTrackerOak";

    std::string collection_id_;
    size_t max_flatbuffer_size_{ DEFAULT_MAX_FLATBUFFER_SIZE };
};

} // namespace core
