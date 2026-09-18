// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_base/full_body_tracker_base.hpp>
#include <deviceio_base/tracker_vendor.hpp>
#include <mcap/tracker_channels.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/full_body_generated.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

namespace core
{

using FullBodyXsensMcapChannels = McapTrackerChannels<FullBodyPoseRecord>;
using FullBodyXsensSchemaTracker = SchemaTracker<FullBodyPoseRecord, FullBodyPose>;

/*!
 * @brief Full-body reader for the Xsens MVN stream pushed by the `xsens_full_body` plugin.
 *
 * Xsens MVN Studio converts its own 23-segment skeleton to the vendor-neutral 24-joint
 * XR_BD_body_tracking layout inside MVN Studio itself (Options -> Network Streamer, preset
 * "Isaac Teleop"), so what arrives here is already a `FullBodyPose` FlatBuffer -- byte-identical
 * to what any other full-body vendor produces. This reader therefore adds nothing but the
 * tensor-collection plumbing, exactly like the other pushed-collection full-body vendors.
 *
 * Two joints are always flagged invalid: MVN has no finger tracking, so LEFT_HAND (22) and
 * RIGHT_HAND (23) carry a copy of the wrist pose with `is_valid = false`, and
 * `all_joint_poses_tracked` is consequently always false. 22 of 24 valid is correct here, not a
 * fault -- consult the per-joint flags.
 */
class LiveFullBodyTrackerXsensImpl : public IFullBodyTrackerImpl
{
public:
    static constexpr std::string_view VENDOR_ID = "body.xsens";
    static constexpr std::string_view DEFAULT_COLLECTION_ID = "xsens_full_body";
    static constexpr std::string_view TENSOR_IDENTIFIER = "full_body_pose";
    //! One pose is 16 B of table/vtable + 24 x 32 B of joint structs = 784 B. 4 KiB leaves room
    //! without over-allocating; the pusher must be configured to match or both sides throw.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 4 * 1024;

    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }

    static void validate_vendor(const TrackerVendor& vendor);

    LiveFullBodyTrackerXsensImpl(const OpenXRSessionHandles& handles,
                                 const TrackerVendor& vendor,
                                 std::unique_ptr<FullBodyXsensMcapChannels> mcap_channels);

    LiveFullBodyTrackerXsensImpl(const LiveFullBodyTrackerXsensImpl&) = delete;
    LiveFullBodyTrackerXsensImpl& operator=(const LiveFullBodyTrackerXsensImpl&) = delete;
    LiveFullBodyTrackerXsensImpl(LiveFullBodyTrackerXsensImpl&&) = delete;
    LiveFullBodyTrackerXsensImpl& operator=(LiveFullBodyTrackerXsensImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const Serialized<FullBodyPose>& get_body_pose() const override;

private:
    std::unique_ptr<FullBodyXsensMcapChannels> mcap_channels_;
    FullBodyXsensSchemaTracker schema_reader_;
    Serialized<FullBodyPose> tracked_;
};

} // namespace core
