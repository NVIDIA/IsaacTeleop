// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/tensor_push_tracker.hpp"

#include <stdexcept>
#include <utility>

namespace core
{

TensorPushTracker::TensorPushTracker(std::string collection_id, std::string tensor_identifier, std::size_t max_payload_size)
    : collection_id_(std::move(collection_id)),
      tensor_identifier_(std::move(tensor_identifier)),
      max_payload_size_(max_payload_size)
{
    if (collection_id_.empty())
    {
        throw std::invalid_argument("TensorPushTracker: collection_id must be non-empty");
    }
    if (tensor_identifier_.empty())
    {
        throw std::invalid_argument("TensorPushTracker: tensor_identifier must be non-empty");
    }
    if (max_payload_size_ == 0)
    {
        throw std::invalid_argument("TensorPushTracker: max_payload_size must be > 0");
    }
}

void TensorPushTracker::push(const ITrackerSession& session, const std::vector<uint8_t>& payload) const
{
    static_cast<const ITensorPushTrackerImpl&>(session.get_tracker_impl(*this)).push(payload);
}

} // namespace core
