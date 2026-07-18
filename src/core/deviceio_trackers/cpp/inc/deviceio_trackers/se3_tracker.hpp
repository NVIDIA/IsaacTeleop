// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/se3_tracker_base.hpp>
#include <schema/se3_tracker_generated.h>

#include <cstddef>
#include <string>
#include <string_view>

namespace core
{

/*!
 * @brief Facade for a generic SE3 (6-DoF pose) tracker device exposed as ``Se3TrackerPoseTrackedT``.
 *
 * Generic across rigid-body pose sources (tracker pucks, mocap rigid bodies, logical trackers
 * derived from other devices, ...): the payload is a single pose plus a validity flag. The
 * reference frame is defined by the data producer (see ``se3_tracker.fbs`` for the normative
 * conventions). A distinct ``collection_id`` per device allows several SE3 trackers to stream
 * simultaneously.
 *
 * After each ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the implementation's tracked snapshot. As with other ``SchemaTracker``-backed trackers,
 * the live backend may retain the last-known sample when a tick has no new samples while the
 * collection remains available (``data`` stays non-null but may be stale); ``data`` is null only
 * when no sample has arrived yet or the collection is unavailable. Independently,
 * ``data->is_valid == false`` means the producer is streaming but tracking is lost — the pose
 * contents are then unspecified.
 *
 * Note: ``collection_id`` (stream instance), ``TENSOR_IDENTIFIER`` (tensor name within the
 * collection), and the MCAP channel names are independent identifiers that happen to share the
 * default spelling ``se3_tracker``.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<Se3Tracker>("se3_tracker");
 * // ... register the tracker with a session, then each tick: ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class Se3Tracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for Se3TrackerPose messages. Pusher and tracker must agree
    //! on this value (it sizes the fixed tensor buffer).
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 256;

    //! Tensor name within the collection. Single source of truth for the pusher/reader wire
    //! rendezvous: both LiveSe3TrackerImpl and producer plugins reference this symbol (a mismatch
    //! is silent no-data).
    static constexpr std::string_view TENSOR_IDENTIFIER = "se3_tracker";

    /*!
     * @brief Constructs an Se3Tracker.
     * @param collection_id Logical stream identifier; must match the device plugin / pusher.
     * @param max_flatbuffer_size Upper bound for serialized ``Se3TrackerPose`` / record payloads.
     */
    explicit Se3Tracker(const std::string& collection_id, size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief SE3 tracker snapshot from the session's implementation.
     *
     * ``tracked.data`` is null when no sample has arrived yet or the collection is unavailable.
     * When non-null, gate on ``data->is_valid`` before consuming ``data->pose`` — the pose is
     * unspecified while tracking is lost.
     */
    const Se3TrackerPoseTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "Se3Tracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
