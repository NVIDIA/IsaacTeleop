// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101/so101_plugin.hpp"

#include "feetech_driver.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/so101_arm_generated.h>

#include <algorithm>
#include <cmath>
#include <iostream>

namespace plugins
{
namespace so101
{

namespace
{
constexpr size_t kMaxFlatbufferSize = 256;
} // namespace

SO101Plugin::SO101Plugin(const std::string& device_port, const std::string& collection_id, int baudrate)
    : device_port_(device_port),
      baudrate_(baudrate),
      driver_(std::make_unique<FeetechDriver>()),
      session_(std::make_shared<core::OpenXRSession>("SO101Plugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "so101_arm",
                                        .localized_name = "SO-101 Robot Arm",
                                        .app_name = "SO101Plugin" })
{
    if (!driver_->open(device_port_, baudrate_))
    {
        throw std::runtime_error("SO101Plugin: Failed to open " + device_port_);
    }
}

SO101Plugin::~SO101Plugin() = default;

void SO101Plugin::update()
{
    if (!driver_->is_open())
    {
        // Attempt to reconnect
        std::cerr << "SO101Plugin: Serial port closed, attempting reconnect to " << device_port_ << std::endl;
        if (!driver_->open(device_port_, baudrate_))
        {
            // Push last known state even on failure
            push_current_state();
            return;
        }
        std::cout << "SO101Plugin: Reconnected to " << device_port_ << std::endl;
    }

    if (!driver_->read_all_positions(positions_))
    {
        // Read failed — connection may be lost. Close so next update() tries reconnect.
        std::cerr << "SO101Plugin: Failed to read servo positions" << std::endl;
        driver_->close();
    }

    push_current_state();
}

void SO101Plugin::push_current_state()
{
    core::SO101ArmOutputT out;
    out.shoulder_pan = normalize_position(positions_[0], centers_[0]);
    out.shoulder_lift = normalize_position(positions_[1], centers_[1]);
    out.elbow_flex = normalize_position(positions_[2], centers_[2]);
    out.wrist_flex = normalize_position(positions_[3], centers_[3]);
    out.wrist_roll = normalize_position(positions_[4], centers_[4]);
    out.gripper = normalize_position(positions_[5], centers_[5]);

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::SO101ArmOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

float SO101Plugin::normalize_position(int raw, int center)
{
    // Raw range: 0-4095 (12-bit), center is the calibrated midpoint.
    // Output: [-1.0, 1.0] where center maps to 0.0.
    // Half-range is the larger of (center, 4095 - center) to avoid asymmetric clipping.
    float half_range = static_cast<float>(std::max(center, 4095 - center));
    if (half_range <= 0.0f)
    {
        return 0.0f;
    }
    float normalized = static_cast<float>(raw - center) / half_range;
    return std::clamp(normalized, -1.0f, 1.0f);
}

} // namespace so101
} // namespace plugins
