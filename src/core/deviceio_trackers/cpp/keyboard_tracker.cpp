// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/keyboard_tracker.hpp"

namespace core
{

// ============================================================================
// KeyboardTracker
// ============================================================================

KeyboardTracker::KeyboardTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

const KeyboardOutputTrackedT& KeyboardTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IKeyboardTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
