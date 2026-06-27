// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/foottroller_tracker_base.hpp>
#include <schema/foottroller_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for foottroller state exposed as ``FoottrollerOutputTrackedT``.
 *
 * Semantic contract: ``stick_x``, ``stick_y``, and others are scalar floats matching the
 * ``FoottrollerOutput`` schema . Units, range,
 * and calibration (e.g. normalized vs raw device values) are defined by the data producer unless
 * documented elsewhere. After each ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the implementation’s tracked snapshot. The live backend (``LiveFoottrollerTrackerImpl::update``)
 * may retain the **last-known** sample when a tick has **no new** samples (e.g. ``m_pending_records`` empty after
 * ``read_all_samples``) while the tensor collection remains available — in that case ``data`` stays non-null but
 * may be **stale** relative to the latest device state. Separately, **absent** data (``data`` null) means no sample
 * has been unpacked yet or the collection/source is unavailable and the implementation has cleared state.
 * Implementations may obtain these values through different
 * backends; transport-specific setup (buffers, extensions, discovery) is documented with the live
 * ``ITrackerImpl`` and session factory.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<FoottrollerTracker>("my_foottroller_collection");
 * // ... register the tracker with a session, then each tick: ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class FoottrollerTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for FoottrollerOutput messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 256;

    /*!
     * @brief Constructs a FoottrollerTracker.
     * @param collection_id Logical stream identifier; must match the data source for the chosen backend
     *        (see live implementation documentation).
     * @param max_flatbuffer_size Upper bound for serialized ``FoottrollerOutput`` / record payloads
     *        (default: 256 bytes); must be sufficient for the schema and backend.
     */
    explicit FoottrollerTracker(const std::string& collection_id,
                                size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }
    /*!
     * @brief Foottroller snapshot from the session’s implementation.
     *
     * ``tracked.data`` is null when there is no valid last-known sample (source never provided data or
     * implementation cleared state when the collection is gone). When non-null, values may still be **unchanged**
     * from the previous ``update()`` if that tick produced no new samples (see ``LiveFoottrollerTrackerImpl``
     * and ``m_pending_records``). When ``tracked.data`` is non-null, nested fields in
     * ``FoottrollerOutputT`` are safe to read.
     */
    const FoottrollerOutputTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "FoottrollerTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
