// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/steering_wheel_tracker_base.hpp>
#include <schema/steering_wheel_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for steering wheel state exposed as ``SteeringWheelOutputTrackedT``.
 *
 * ``SteeringWheelOutput`` uses normalized joystick axis values independent of a specific wheel model.
 * Producers should map raw device axes into [-1, 1] before publishing.
 */
class SteeringWheelTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for SteeringWheelOutput messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 1024;

    explicit SteeringWheelTracker(const std::string& collection_id,
                                  size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    const SteeringWheelOutputTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "SteeringWheelTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
