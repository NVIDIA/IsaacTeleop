// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/joint_state_tracker_base.hpp>
#include <schema/joint_state_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for a generic joint-space device exposed as ``JointStateOutputTrackedT``.
 *
 * Generic across joint-space input devices (leader arms, exoskeletons, gloves, ...): the payload
 * is a list of named joints (``JointStateOutput.joints``, keyed by ``JointState.name``) plus an
 * optional end-effector pose. The semantics of each joint (units, calibration) are defined by the
 * data producer (the device plugin). A distinct ``collection_id`` per device allows several
 * joint-space devices to stream simultaneously.
 *
 * After each ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the implementation's tracked snapshot. As with other ``SchemaTracker``-backed trackers,
 * the live backend may retain the last-known sample when a tick has no new samples while the
 * collection remains available (``data`` stays non-null but may be stale); ``data`` is null only
 * when no sample has arrived yet or the collection is unavailable.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<JointStateTracker>("so101_leader");
 * // ... register the tracker with a session, then each tick: ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class JointStateTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for JointStateOutput messages.
    //! Large enough for a few dozen named joints with optional velocity/effort. Pusher and tracker
    //! must agree on this value (it sizes the fixed tensor buffer).
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 4096;

    /*!
     * @brief Constructs a JointStateTracker.
     * @param collection_id Logical stream identifier; must match the device plugin / pusher.
     * @param max_flatbuffer_size Upper bound for serialized ``JointStateOutput`` / record payloads.
     */
    explicit JointStateTracker(const std::string& collection_id,
                               size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Joint-state snapshot from the session's implementation.
     *
     * ``tracked.data`` is null when no valid sample exists. When non-null, the nested
     * ``JointStateOutputT`` (joints, device_id, optional ee_pose) is safe to read.
     */
    const JointStateOutputTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "JointStateTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
