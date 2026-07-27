// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/haptic_command_reader_tracker.hpp"

#include <stdexcept>

namespace core
{

HapticCommandReaderTracker::HapticCommandReaderTracker(const std::string& collection_id, std::size_t max_payload_size)
    : collection_id_(collection_id), max_payload_size_(max_payload_size)
{
    if (collection_id_.empty())
    {
        throw std::invalid_argument("HapticCommandReaderTracker: collection_id must be non-empty");
    }
    if (max_payload_size_ == 0)
    {
        throw std::invalid_argument("HapticCommandReaderTracker: max_payload_size must be > 0");
    }
}

const HapticCommandTrackedT& HapticCommandReaderTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IHapticCommandReaderTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

const HapticCommandTrackedT& HapticCommandReaderTracker::get_data(const ITrackerSession& session,
                                                                  std::string_view endpoint) const
{
    return static_cast<const IHapticCommandReaderTrackerImpl&>(session.get_tracker_impl(*this)).get_data(endpoint);
}

} // namespace core
