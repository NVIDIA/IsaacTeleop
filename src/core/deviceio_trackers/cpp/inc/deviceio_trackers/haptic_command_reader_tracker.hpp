// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/haptic_command_reader_tracker_base.hpp>
#include <schema/haptic_command_generated.h>

#include <cstddef>
#include <string>
#include <string_view>

namespace core
{

// Consumer ITracker (plugin side): reads the most-recent HapticCommand
// FlatBuffer pushed by a TensorPushTracker on the same `collection_id`
// (the producer encodes a HapticCommand and pushes it under the canonical
// "haptic_command" tensor identifier). A vendor plugin reuses this directly
// instead of writing its own SchemaTracker boilerplate.
class HapticCommandReaderTracker : public ITracker
{
public:
    static constexpr std::size_t DEFAULT_MAX_PAYLOAD_SIZE = 256;

    explicit HapticCommandReaderTracker(const std::string& collection_id,
                                        std::size_t max_payload_size = DEFAULT_MAX_PAYLOAD_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // `tracked.data` is null until the first sample arrives or after the
    // producer collection disappears from the tensor list.
    const HapticCommandTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    std::size_t max_payload_size() const
    {
        return max_payload_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "HapticCommandReaderTracker";

    std::string collection_id_;
    std::size_t max_payload_size_{ DEFAULT_MAX_PAYLOAD_SIZE };
};

} // namespace core
