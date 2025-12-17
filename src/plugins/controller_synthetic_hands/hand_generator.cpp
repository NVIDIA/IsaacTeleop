// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Hand joint generation

#include <algorithm>
#include <cmath>
#include <hand_generator.hpp>

namespace plugins
{
namespace controller_synthetic_hands
{

void HandGenerator::generate(XrHandJointLocationEXT* joints, const XrPosef& wrist_pose, bool is_left_hand, float curl)
{
    calculate_positions(joints, wrist_pose, is_left_hand, curl);
    calculate_orientations(joints, wrist_pose);
}

void HandGenerator::generate_relative(XrHandJointLocationEXT* joints, bool is_left_hand, float curl)
{
    // Generate hand joints in controller-relative space (identity pose at origin)
    XrPosef identity_pose;
    identity_pose.position = { 0.0f, 0.0f, 0.0f };
    identity_pose.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };

    calculate_positions(joints, identity_pose, is_left_hand, curl);
    calculate_orientations(joints, identity_pose);
}

void HandGenerator::calculate_positions(XrHandJointLocationEXT* joints,
                                        const XrPosef& wrist_pose,
                                        bool is_left_hand,
                                        float curl)
{
    // Joint offsets in meters - OpenXR coordinate system: X+ = right, Y+ = up, Z- = forward
    // Left hand: X+ = thumb side (right from palm), Y+ = up (back of hand), Z- = forward (fingers point)
    const Vec3 offsets[XR_HAND_JOINT_COUNT_EXT] = { { 0.0f, 0.015f, -0.035f }, // Palm (slightly up and forward from
                                                                               // wrist)
                                                    { 0.0f, 0.0f, 0.0f }, // Wrist
                                                    // Thumb (extends outward and forward)
                                                    { 0.025f, 0.005f, -0.015f },
                                                    { 0.035f, 0.010f, -0.030f },
                                                    { 0.040f, 0.012f, -0.050f },
                                                    { 0.042f, 0.013f, -0.062f },
                                                    // Index finger (forward)
                                                    { 0.018f, 0.003f, -0.055f },
                                                    { 0.020f, 0.000f, -0.095f },
                                                    { 0.020f, 0.000f, -0.125f },
                                                    { 0.019f, 0.000f, -0.145f },
                                                    { 0.019f, 0.000f, -0.155f },
                                                    // Middle finger (forward)
                                                    { 0.005f, 0.002f, -0.055f },
                                                    { 0.005f, 0.000f, -0.100f },
                                                    { 0.005f, 0.000f, -0.135f },
                                                    { 0.005f, 0.000f, -0.160f },
                                                    { 0.005f, 0.000f, -0.175f },
                                                    // Ring finger (forward)
                                                    { -0.008f, 0.003f, -0.055f },
                                                    { -0.010f, 0.000f, -0.095f },
                                                    { -0.012f, 0.000f, -0.128f },
                                                    { -0.013f, 0.000f, -0.150f },
                                                    { -0.014f, 0.000f, -0.163f },
                                                    // Little finger (forward)
                                                    { -0.022f, 0.005f, -0.050f },
                                                    { -0.025f, 0.000f, -0.080f },
                                                    { -0.027f, 0.000f, -0.103f },
                                                    { -0.029f, 0.000f, -0.120f },
                                                    { -0.030f, 0.000f, -0.130f } };

    // Curl parameters: apply curling to fingers based on trigger value (0.0 = open, 1.0 = closed)
    const float curl_clamped = std::max(0.0f, std::min(1.0f, curl));

    for (int i = 0; i < XR_HAND_JOINT_COUNT_EXT; i++)
    {
        Vec3 offset = offsets[i];

        // Apply finger curling (joints 6-26 are fingers, excluding palm/wrist)
        if (i >= 6) // All finger joints
        {
            // Calculate which finger and segment
            int finger_start[] = { 6, 11, 16, 21 }; // Index, Middle, Ring, Little
            int finger_idx = -1;
            for (int f = 0; f < 4; f++)
            {
                if (i >= finger_start[f] && i < finger_start[f] + 5)
                {
                    finger_idx = f;
                    break;
                }
            }

            if (finger_idx >= 0)
            {
                int segment_in_finger = i - finger_start[finger_idx];
                // Curl fingers by moving them toward palm (reduce Z, reduce Y for further segments)
                float curl_amount = curl_clamped * (0.3f + 0.15f * segment_in_finger);
                offset.z += curl_amount * 0.04f; // Pull back toward palm
                offset.y -= curl_amount * 0.02f * segment_in_finger; // Curl downward
            }
        }
        // Curl thumb (joints 2-5)
        else if (i >= 2 && i <= 5)
        {
            int thumb_segment = i - 2;
            float curl_amount = curl_clamped * (0.2f + 0.1f * thumb_segment);
            offset.z += curl_amount * 0.03f; // Pull back
            offset.x *= (1.0f - curl_clamped * 0.3f); // Move closer to palm
        }

        if (!is_left_hand)
            offset.x = -offset.x; // Mirror for right hand

        XrVector3f offset_vec = { offset.x, offset.y, offset.z };
        XrVector3f rotated = rotate_vector(offset_vec, wrist_pose.orientation);

        joints[i].pose.position.x = wrist_pose.position.x + rotated.x;
        joints[i].pose.position.y = wrist_pose.position.y + rotated.y;
        joints[i].pose.position.z = wrist_pose.position.z + rotated.z;
        joints[i].pose.orientation = wrist_pose.orientation;

        // Set radius based on joint type
        if (i <= 1)
            joints[i].radius = 0.015f; // Palm/wrist
        else if (i == 5 || i == 10 || i == 15 || i == 20 || i == 25)
            joints[i].radius = 0.006f; // Tips
        else if (i == 3 || i == 4 || i == 9 || i == 14 || i == 19 || i == 24)
            joints[i].radius = 0.008f; // Distal
        else if (i == 8 || i == 13 || i == 18 || i == 23)
            joints[i].radius = 0.010f; // Intermediate
        else
            joints[i].radius = 0.012f; // Proximal/metacarpal

        joints[i].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                                  XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
    }
}

void HandGenerator::calculate_orientations(XrHandJointLocationEXT* joints, const XrPosef& wrist_pose)
{
    XrVector3f hand_up = rotate_vector({ 0.0f, 1.0f, 0.0f }, wrist_pose.orientation);

    const int finger_chains[][5] = {
        { 2, 3, 4, 5, -1 }, { 6, 7, 8, 9, 10 }, { 11, 12, 13, 14, 15 }, { 16, 17, 18, 19, 20 }, { 21, 22, 23, 24, 25 }
    };

    for (int finger = 0; finger < 5; finger++)
    {
        for (int segment = 0; segment < 4; segment++)
        {
            int curr = finger_chains[finger][segment];
            int next = finger_chains[finger][segment + 1];
            if (next == -1)
                break;

            XrVector3f dir = { joints[next].pose.position.x - joints[curr].pose.position.x,
                               joints[next].pose.position.y - joints[curr].pose.position.y,
                               joints[next].pose.position.z - joints[curr].pose.position.z };
            joints[curr].pose.orientation = quaternion_look_at(dir, hand_up);
        }

        int tip = finger_chains[finger][4];
        int distal = finger_chains[finger][3];
        if (tip > 0 && distal > 0)
        {
            joints[tip].pose.orientation = joints[distal].pose.orientation;
        }
    }

    // Palm orientation
    XrVector3f palm_dir = { joints[11].pose.position.x - joints[0].pose.position.x,
                            joints[11].pose.position.y - joints[0].pose.position.y,
                            joints[11].pose.position.z - joints[0].pose.position.z };
    joints[0].pose.orientation = quaternion_look_at(palm_dir, hand_up);
}

XrVector3f HandGenerator::rotate_vector(const XrVector3f& v, const XrQuaternionf& q)
{
    float t1 = 2.0f * (q.y * v.z - q.z * v.y);
    float t2 = 2.0f * (q.z * v.x - q.x * v.z);
    float t3 = 2.0f * (q.x * v.y - q.y * v.x);
    return { v.x + q.w * t1 + (q.y * t3 - q.z * t2), v.y + q.w * t2 + (q.z * t1 - q.x * t3),
             v.z + q.w * t3 + (q.x * t2 - q.y * t1) };
}

XrQuaternionf HandGenerator::quaternion_look_at(const XrVector3f& direction, const XrVector3f& up)
{
    float dir_len = std::sqrt(direction.x * direction.x + direction.y * direction.y + direction.z * direction.z);
    if (dir_len < 0.0001f)
        return { 0.0f, 0.0f, 0.0f, 1.0f };

    XrVector3f forward = { direction.x / dir_len, direction.y / dir_len, direction.z / dir_len };
    XrVector3f right = { up.y * forward.z - up.z * forward.y, up.z * forward.x - up.x * forward.z,
                         up.x * forward.y - up.y * forward.x };

    float right_len = std::sqrt(right.x * right.x + right.y * right.y + right.z * right.z);
    if (right_len < 0.0001f)
    {
        right = { 1.0f, 0.0f, 0.0f };
    }
    else
    {
        right.x /= right_len;
        right.y /= right_len;
        right.z /= right_len;
    }

    XrVector3f actual_up = { forward.y * right.z - forward.z * right.y, forward.z * right.x - forward.x * right.z,
                             forward.x * right.y - forward.y * right.x };

    float m00 = right.x, m01 = right.y, m02 = right.z;
    float m10 = actual_up.x, m11 = actual_up.y, m12 = actual_up.z;
    float m20 = forward.x, m21 = forward.y, m22 = forward.z;

    float trace = m00 + m11 + m22;
    XrQuaternionf q;

    if (trace > 0.0f)
    {
        float s = 0.5f / std::sqrt(trace + 1.0f);
        q.w = 0.25f / s;
        q.x = (m21 - m12) * s;
        q.y = (m02 - m20) * s;
        q.z = (m10 - m01) * s;
    }
    else if (m00 > m11 && m00 > m22)
    {
        float s = 2.0f * std::sqrt(1.0f + m00 - m11 - m22);
        q.w = (m21 - m12) / s;
        q.x = 0.25f * s;
        q.y = (m01 + m10) / s;
        q.z = (m02 + m20) / s;
    }
    else if (m11 > m22)
    {
        float s = 2.0f * std::sqrt(1.0f + m11 - m00 - m22);
        q.w = (m02 - m20) / s;
        q.x = (m01 + m10) / s;
        q.y = 0.25f * s;
        q.z = (m12 + m21) / s;
    }
    else
    {
        float s = 2.0f * std::sqrt(1.0f + m22 - m00 - m11);
        q.w = (m10 - m01) / s;
        q.x = (m02 + m20) / s;
        q.y = (m12 + m21) / s;
        q.z = 0.25f * s;
    }

    return q;
}

} // namespace controller_synthetic_hands
} // namespace plugins
