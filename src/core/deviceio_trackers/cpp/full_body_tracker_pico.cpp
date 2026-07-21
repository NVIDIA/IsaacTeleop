// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/full_body_tracker_pico.hpp"

#include <stdexcept>

namespace core
{

// ============================================================================
// FullBodyTrackerPico Public Interface
// ============================================================================

FullBodyTrackerPico::FullBodyTrackerPico(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
    if (collection_id_.empty())
    {
        throw std::invalid_argument("FullBodyTrackerPico: collection_id must not be empty");
    }
    if (max_flatbuffer_size_ == 0)
    {
        throw std::invalid_argument("FullBodyTrackerPico: max_flatbuffer_size must be greater than zero");
    }
}

const FullBodyPosePicoTrackedT& FullBodyTrackerPico::get_body_pose(const ITrackerSession& session) const
{
    return static_cast<const IFullBodyTrackerPicoImpl&>(session.get_tracker_impl(*this)).get_body_pose();
}

} // namespace core
