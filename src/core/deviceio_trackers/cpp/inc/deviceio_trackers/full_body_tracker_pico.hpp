// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_pico_base.hpp>
#include <schema/full_body_generated.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
namespace core
{

// Full body tracker for PICO devices using XR_BD_body_tracking.
// Tracks 24 body joints (indices 0-23) from pelvis to hands.
class FullBodyTrackerPico : public ITracker
{
public:
    //! Number of joints in XR_BD_body_tracking (0-23).
    static constexpr uint32_t JOINT_COUNT = 24;

    //! Default maximum FlatBuffer size for schema-pushed FullBodyPosePico samples.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 16 * 1024;

    //! Tensor name used when consuming schema-pushed FullBodyPosePico samples.
    static constexpr std::string_view TENSOR_IDENTIFIER = "full_body";

    //! Default mode reads native XR_BD_body_tracking samples from the OpenXR runtime.
    FullBodyTrackerPico() = default;

    //! External mode reads FullBodyPosePico samples from an OpenXR tensor collection.
    explicit FullBodyTrackerPico(const std::string& collection_id,
                                 size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Query method:
    // - tracked.data is null when the body tracker is inactive.
    // - when tracked.data is non-null, nested fields in FullBodyPosePicoT are safe to read.
    const FullBodyPosePicoTrackedT& get_body_pose(const ITrackerSession& session) const;

    bool uses_external_collection() const
    {
        return !collection_id_.empty();
    }

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "FullBodyTrackerPico";

    std::string collection_id_;
    size_t max_flatbuffer_size_ = DEFAULT_MAX_FLATBUFFER_SIZE;
};

} // namespace core
