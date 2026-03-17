// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/full_body_tracker_pico.hpp"

#include <deviceio_base/tracker_factory.hpp>
#include <schema/full_body_bfbs_generated.h>

namespace core
{

// ============================================================================
// FullBodyTrackerPico Public Interface
// ============================================================================

std::vector<std::string> FullBodyTrackerPico::get_required_extensions() const
{
    return { XR_BD_BODY_TRACKING_EXTENSION_NAME };
}

std::string_view FullBodyTrackerPico::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(FullBodyPosePicoRecordBinarySchema::data()),
                            FullBodyPosePicoRecordBinarySchema::size());
}

const FullBodyPosePicoTrackedT& FullBodyTrackerPico::get_body_pose(const ITrackerSession& session) const
{
    return static_cast<const FullBodyTrackerPicoImpl&>(session.get_tracker_impl(*this)).get_body_pose();
}

std::unique_ptr<ITrackerImpl> FullBodyTrackerPico::create_tracker_impl(ITrackerFactory& factory) const
{
    return factory.create_full_body_tracker_pico_impl(this);
}

} // namespace core
