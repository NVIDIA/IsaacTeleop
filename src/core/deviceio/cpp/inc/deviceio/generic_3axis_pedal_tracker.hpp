// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_tracker.hpp"
#include "tracker.hpp"

#include <schema/pedals_generated.h>

#include <memory>
#include <string>

namespace core
{

/*!
 * @brief Tracker for reading Generic3AxisPedalOutput FlatBuffer messages via OpenXR tensor extensions.
 *
 * This tracker reads foot pedal outputs (left_pedal, right_pedal, rudder) pushed by a remote application
 * using the SchemaTracker utility. Both pusher and reader must agree on the
 * collection_id and use the Generic3AxisPedalOutput schema.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<Generic3AxisPedalTracker>("my_pedal_collection");
 * // ... create DeviceIOSession with tracker ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class Generic3AxisPedalTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for Generic3AxisPedalOutput messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 256;

    /*!
     * @brief Constructs a Generic3AxisPedalTracker.
     * @param collection_id Tensor collection identifier for discovery.
     * @param max_flatbuffer_size Maximum serialized FlatBuffer size (default: 256 bytes).
     */
    explicit Generic3AxisPedalTracker(const std::string& collection_id,
                                      size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    // ITracker interface
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override;
    std::string_view get_schema_name() const override;
    std::string_view get_schema_text() const override;

    /*!
     * @brief Get the current foot pedal data.
     */
    const Generic3AxisPedalOutputT& get_data(const DeviceIOSession& session) const;

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
