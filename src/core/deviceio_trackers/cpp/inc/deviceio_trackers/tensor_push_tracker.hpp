// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tensor_push_tracker_base.hpp>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

// Generic producer ITracker: pushes opaque serialised payloads as tensor
// samples over XR_NVX1_push_tensor. The payload's schema is the caller's
// concern -- this tracker is schema-agnostic, so any cross-process output
// device (haptic glove, exoskeleton, ...) reuses it without writing a new
// C++ tracker. Pairs with a consumer (e.g. a SchemaTracker / a
// HapticCommandReaderTracker) on the same `collection_id` + `tensor_identifier`.
class TensorPushTracker : public ITracker
{
public:
    static constexpr std::size_t DEFAULT_MAX_PAYLOAD_SIZE = 256;

    // `collection_id` pairs producer and consumer across processes;
    // `tensor_identifier` names the tensor within the collection (must match
    // the consumer); `max_payload_size` is the fixed per-sample buffer size.
    TensorPushTracker(std::string collection_id,
                      std::string tensor_identifier,
                      std::size_t max_payload_size = DEFAULT_MAX_PAYLOAD_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // `payload.size()` must be <= max_payload_size(); the impl pads to the
    // per-sample size declared at collection-create time.
    void push(const ITrackerSession& session, const std::vector<uint8_t>& payload) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    const std::string& tensor_identifier() const
    {
        return tensor_identifier_;
    }

    std::size_t max_payload_size() const
    {
        return max_payload_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "TensorPushTracker";

    std::string collection_id_;
    std::string tensor_identifier_;
    std::size_t max_payload_size_{ DEFAULT_MAX_PAYLOAD_SIZE };
};

} // namespace core
