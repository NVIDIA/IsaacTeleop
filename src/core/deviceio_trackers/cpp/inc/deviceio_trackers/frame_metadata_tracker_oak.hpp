// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/frame_metadata_tracker_oak_base.hpp>

#include <cstddef>
#include <string>
#include <string_view>

namespace core
{

/*!
 * @brief Tracker for one OAK camera stream's FrameMetadataOak.
 *
 * One tracker instance tracks one stream, identified by the tensor collection the
 * OAK plugin publishes it under: "{collection_prefix}/{StreamName}", where
 * collection_prefix is the plugin's --collection-prefix argument and StreamName is
 * the StreamType enum name ("Color", "MonoLeft", "MonoRight"). Create one tracker
 * per stream you care about.
 *
 * Usage:
 * @code
 * auto color = std::make_shared<FrameMetadataTrackerOak>("oak_camera/Color");
 * auto mono = std::make_shared<FrameMetadataTrackerOak>("oak_camera/MonoLeft");
 * // ... create session with both trackers ...
 * session->update();
 * const auto& tracked = color->get_data(*session);
 * if (tracked.data)
 *     std::cout << "seq=" << tracked.data->sequence_number << std::endl;
 * @endcode
 */
class FrameMetadataTrackerOak : public ITracker
{
public:
    //! Default maximum FlatBuffer size for individual FrameMetadataOak messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 128;

    /*!
     * @brief Constructs a tracker for a single OAK stream.
     * @param collection_id Tensor collection carrying this stream's metadata,
     *        e.g. "oak_camera/Color".
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size (default: 128 bytes).
     */
    explicit FrameMetadataTrackerOak(const std::string& collection_id,
                                     size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Get this stream's frame metadata.
     * @param session Active ITrackerSession.
     * @return Reference to the FrameMetadataOakTrackedT for this stream.
     *         The inner @c data pointer is null until the first frame arrives.
     *         When @c data is non-null, nested fields in FrameMetadataOakT are
     *         safe to read.
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
    size_t max_flatbuffer_size_;
};

} // namespace core
