// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_tracker.hpp"
#include "tracker.hpp"

#include <schema/camera_generated.h>

#include <memory>
#include <string>

namespace core
{

/*!
 * @brief Tracker for reading FrameMetadata FlatBuffer messages via OpenXR tensor extensions.
 *
 * This tracker reads frame metadata (timestamp, sequence_number) pushed by a camera plugin
 * using the SchemaTracker infrastructure. Both pusher and reader must agree on the
 * collection_id and use the FrameMetadata schema from camera.fbs.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<FrameMetadataTracker>("camera_collection_id");
 * // ... create DeviceIOSession with tracker ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class FrameMetadataTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for FrameMetadata messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 128;

    /*!
     * @brief Constructs a FrameMetadataTracker.
     * @param collection_id Tensor collection identifier for discovery.
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size (default: 128 bytes).
     */
    explicit FrameMetadataTracker(const std::string& collection_id,
                                  size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override;
    std::string_view get_schema_name() const override;
    std::string_view get_schema_text() const override;

    /*!
     * @brief Get the current frame metadata.
     */
    const FrameMetadataT& get_data(const DeviceIOSession& session) const;

protected:
    const SchemaTrackerConfig& get_config() const;

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    SchemaTrackerConfig m_config;
    class Impl;
};

} // namespace core
