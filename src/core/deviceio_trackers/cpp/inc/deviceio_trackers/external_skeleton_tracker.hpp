// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/external_skeleton_tracker_base.hpp>
#include <schema/external_skeleton_generated.h>

#include <cstddef>
#include <cstdint>
#include <string>

namespace core
{

/*!
 * @brief Facade for an external upper-body / arm-gesture skeleton, exposed as
 *        ``ExternalSkeletonPoseTrackedT``.
 *
 * The tracker is vendor-neutral: its data source is a separate plugin process
 * (e.g. ``external_skeleton_plugin``) that reads from a third-party mocap
 * device (Rokoko Smartsuit, Xsens / Movella MVN, Sony mocopi, Noitom
 * Perception Neuron, OptiTrack, etc.) and pushes ``ExternalSkeletonPose``
 * FlatBuffers via ``XR_NVX1_push_tensor``. The live backend reads them via
 * ``XR_NVX1_tensor_data`` (see ``LiveExternalSkeletonTrackerImpl``).
 *
 * Joint layout follows ``ExternalSkeletonJoint`` (14 upper-body joints).
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<ExternalSkeletonTracker>("rokoko_skeleton");
 * // ... register with a session, then each tick:
 * session->update();
 * const auto& tracked = tracker->get_skeleton_pose(*session);
 * if (tracked.data) {
 *     // safe to read tracked.data->joints, source_id, etc.
 * }
 * @endcode
 */
class ExternalSkeletonTracker : public ITracker
{
public:
    //! Number of joints in the ExternalSkeletonJoint layout.
    static constexpr uint32_t JOINT_COUNT = 14;

    //! Default maximum FlatBuffer size for ExternalSkeletonPose messages.
    //! Sized for 14 BodyJointPose entries + flags + a short source_id string.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 2048;

    /*!
     * @brief Constructs an ExternalSkeletonTracker.
     * @param collection_id Logical stream identifier; must match the
     *        ``collection_id`` used by the upstream plugin's ``SchemaPusher``.
     * @param max_flatbuffer_size Upper bound for serialized
     *        ``ExternalSkeletonPose`` / record payloads. Must be at least as
     *        large as the value the plugin uses.
     */
    explicit ExternalSkeletonTracker(const std::string& collection_id,
                                     size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Skeleton snapshot from the session's implementation.
     *
     * ``tracked.data`` is null when no sample has been received yet or the
     * upstream plugin's tensor collection is unavailable. When non-null,
     * nested fields are safe to read; values may be unchanged from the
     * previous tick if the device produced no new samples this frame.
     */
    const ExternalSkeletonPoseTrackedT& get_skeleton_pose(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "ExternalSkeletonTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
