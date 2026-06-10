// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <cstdint>
#include <memory>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace so101_leader
{

/*!
 * @brief Streams SO-101 (5-DOF + gripper) leader-arm joint angles as ``JointStateOutput`` via
 *        OpenXR ``SchemaPusher``, on the generic joint-space device path.
 *
 * The SO-101 reads 6 Feetech STS3215 bus servos over a serial port (LeRobot's ``FeetechMotorsBus``
 * + calibration). To keep the example hardware-free and headless, this plugin ships a
 * **synthetic backend** that emits a smooth joint trajectory; ``read_hardware()`` is the marked
 * seam where a real serial/Feetech read replaces the synthetic values.
 */
class So101LeaderPlugin
{
public:
    /*!
     * @param device_path Serial device path (e.g. /dev/ttyACM0) for the real Feetech backend
     *        (see read_hardware()); the synthetic backend ignores it. Empty for synthetic-only.
     * @param collection_id Tensor collection id; must match the consumer's JointStateTracker.
     *        Also used as the JointStateOutput.device_id.
     */
    So101LeaderPlugin(const std::string& device_path, const std::string& collection_id);
    ~So101LeaderPlugin();

    void update();

private:
    // Fill positions_ (in kJointNames order) with the latest joint angles. This reference ships a
    // synthetic trajectory; SEAM: replace the body with a real Feetech/serial read for hardware.
    void read_hardware();
    void push_current_state();

    std::string device_path_;
    std::string collection_id_;
    int64_t frame_ = 0;
    double positions_[6] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace so101_leader
} // namespace plugins
