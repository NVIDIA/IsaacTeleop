// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <memory>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace so101
{

class FeetechDriver;

/*!
 * @brief Reads joint positions from an SO-101 6-DOF robot arm via Feetech
 *        STS3215 serial bus servos, normalizes them, and pushes SO101ArmOutput
 *        via OpenXR SchemaPusher.
 *
 * The SO-101 has 6 joints:
 *   - shoulder_pan  (Servo ID 1)
 *   - shoulder_lift (Servo ID 2)
 *   - elbow_flex    (Servo ID 3)
 *   - wrist_flex    (Servo ID 4)
 *   - wrist_roll    (Servo ID 5)
 *   - gripper       (Servo ID 6)
 *
 * Raw positions (0-4095) are normalized to [-1.0, 1.0] centered on the
 * calibration midpoint (default 2048).
 */
class SO101Plugin
{
public:
    /*!
     * @brief Construct the plugin and connect to the SO-101 arm.
     * @param device_port Serial port path (e.g., "/dev/ttyACM0").
     * @param collection_id OpenXR tensor collection identifier.
     * @param baudrate Serial baudrate (default 1000000).
     */
    SO101Plugin(const std::string& device_port, const std::string& collection_id, int baudrate = 1000000);
    ~SO101Plugin();

    /*!
     * @brief Read current joint positions and push to OpenXR.
     *
     * If the serial connection is lost, attempts to reopen it.
     * Always pushes the latest known state (even on read failure).
     */
    void update();

private:
    /*!
     * @brief Build and push an SO101ArmOutput FlatBuffer with the current positions.
     */
    void push_current_state();

    /*!
     * @brief Normalize a raw servo position to [-1.0, 1.0].
     * @param raw Raw position value (0-4095).
     * @param center Calibration center position (default 2048).
     * @return Normalized position in [-1.0, 1.0].
     */
    static float normalize_position(int raw, int center = 2048);

    std::string device_port_;
    int baudrate_;
    std::unique_ptr<FeetechDriver> driver_;
    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;

    int positions_[6] = { 0, 0, 0, 0, 0, 0 };

    // Calibration centers for each joint (default to midpoint 2048)
    int centers_[6] = { 2048, 2048, 2048, 2048, 2048, 2048 };
};

} // namespace so101
} // namespace plugins
