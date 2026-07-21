// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/oglo_tactile_tracker_base.hpp>
#include <schema/oglo_tactile_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for one OGLO tactile glove exposed as ``OgloGloveSampleTrackedT``.
 *
 * Reads a tensor collection pushed by the ``oglo_tactile`` plugin
 * (``--collection-prefix``). One tracker per hand: construct with the matching
 * ``collection_id`` (e.g. ``"oglo/left"`` / ``"oglo/right"``). After each
 * ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the latest decoded sample; ``data`` is null until the first sample
 * arrives or when the collection is unavailable.
 *
 * Usage:
 * @code
 * auto glove = std::make_shared<OgloTactileTracker>("oglo/right");
 * // ... register with a session, then each tick: ...
 * session->update();
 * const auto& tracked = glove->get_data(*session);
 * if (tracked.data) { auto& taxels = tracked.data->taxels; ... }
 * @endcode
 */
class OgloTactileTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for OgloGloveSample messages
    //! (80 taxels x 2B + 6 IMU x 2B + table overhead).
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 512;

    /*!
     * @brief Constructs an OgloTactileTracker.
     * @param collection_id Tensor collection identifier; must match the
     *        ``oglo_tactile`` plugin's ``--collection-prefix`` + "/" + side.
     * @param max_flatbuffer_size Upper bound for serialized payloads (default 512).
     */
    explicit OgloTactileTracker(const std::string& collection_id,
                                size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Glove snapshot from the session's implementation.
     * @c tracked.data is null when no valid sample is available; when non-null,
     * @c data->taxels (80 values) and the IMU fields are safe to read.
     */
    const OgloGloveSampleTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "OgloTactileTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
