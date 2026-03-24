// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/full_body_tracker_pico.hpp"

namespace core
{

// ============================================================================
// FullBodyTrackerPico Public Interface
// ============================================================================

const FullBodyPosePicoTrackedT& FullBodyTrackerPico::get_body_pose(const ITrackerSession& session) const
{
    return static_cast<const IFullBodyTrackerPicoImpl&>(session.get_tracker_impl(*this)).get_body_pose();
}

} // namespace core
