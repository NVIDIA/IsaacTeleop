// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_tracker.hpp"
#include "tracker.hpp"

#include <schema/haply_device_generated.h>

#include <memory>
#include <string>

namespace core
{

/*!
 * @brief Tracker for reading HaplyDeviceOutput FlatBuffer messages via OpenXR tensor extensions.
 *
 * This tracker reads Haply Inverse3 + VerseGrip device state (cursor position,
 * velocity, orientation, buttons) pushed by the Haply plugin using the
 * SchemaTracker utility. Both pusher and reader must agree on the collection_id
 * and use the HaplyDeviceOutput schema.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<HaplyDeviceTracker>("haply_device");
 * // ... create DeviceIOSession with tracker ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class HaplyDeviceTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for HaplyDeviceOutput messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 256;

    /*!
     * @brief Constructs a HaplyDeviceTracker.
     * @param collection_id Tensor collection identifier for discovery.
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size (default: 256 bytes).
     */
    explicit HaplyDeviceTracker(const std::string& collection_id = "haply_device",
                                size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override;
    std::string_view get_schema_name() const override;
    std::string_view get_schema_text() const override;

    std::vector<std::string> get_record_channels() const override
    {
        return {"haply_device"};
    }

    /*!
     * @brief Get the current Haply device data (tracked.data is null when no data available).
     */
    const HaplyDeviceOutputTrackedT& get_data(const DeviceIOSession& session) const;

protected:
    /*!
     * @brief Access the configuration for subclass use.
     */
    const SchemaTrackerConfig& get_config() const;

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    SchemaTrackerConfig m_config;

    class Impl;
};

} // namespace core
