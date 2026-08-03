// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/generic_3axis_pedal_tracker_base.hpp>
#include <schema/pedals_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for three-axis pedal state exposed as ``Serialized<Generic3AxisPedalOutput>``.
 *
 * Semantic contract: ``left_pedal``, ``right_pedal``, and ``rudder`` are scalar floats matching the
 * ``Generic3AxisPedalOutput`` schema (axis semantics are left/right/rudder as named). Units, range,
 * and calibration (e.g. normalized vs raw device values) are defined by the data producer unless
 * documented elsewhere. After each ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the implementation’s tracked snapshot. The live backend (``LiveGeneric3AxisPedalTrackerImpl::update``)
 * may retain the **last-known** sample when a tick has **no new** samples while the tensor collection remains
 * available — in that case the handle stays non-empty but may be **stale** relative to the latest device state.
 * Separately, an **empty** handle means no sample has arrived yet or the collection/source is unavailable and
 * the implementation has cleared state.
 * Implementations may obtain these values through different
 * backends; transport-specific setup (buffers, extensions, discovery) is documented with the live
 * ``ITrackerImpl`` and session factory.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<Generic3AxisPedalTracker>("my_pedal_collection");
 * // ... register the tracker with a session, then each tick: ...
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
     * @param collection_id Logical stream identifier; must match the data source for the chosen backend
     *        (see live implementation documentation).
     * @param max_flatbuffer_size Upper bound for serialized ``Generic3AxisPedalOutput`` / record payloads
     *        (default: 256 bytes); must be sufficient for the schema and backend.
     */
    explicit Generic3AxisPedalTracker(const std::string& collection_id,
                                      size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }
    /*!
     * @brief Pedal snapshot from the session’s implementation.
     *
     * The handle is empty when there is no valid last-known sample (source never provided data or
     * implementation cleared state when the collection is gone). When non-empty, values may still be
     * **unchanged** from the previous ``update()`` if that tick produced no new samples (see
     * ``LiveGeneric3AxisPedalTrackerImpl`` and ``m_pending_records``); nested fields in
     * ``Generic3AxisPedalOutput`` are safe to read.
     */
    const Serialized<Generic3AxisPedalOutput>& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "Generic3AxisPedalTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
