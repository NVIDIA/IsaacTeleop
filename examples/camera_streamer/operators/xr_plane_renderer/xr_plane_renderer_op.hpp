// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "holoscan/holoscan.hpp"
#include "holoscan/utils/cuda_stream_handler.hpp"

#include <memory>
#include <string>
#include <vector>

// XR headers from holohub
#include "xr_composition_layers.hpp"
#include "xr_session.hpp"
#include "xr_swapchain_cuda.hpp"

// Holoviz
#include "holoviz/holoviz.hpp"

// Camera plane tracking
#include "camera_plane.hpp"

namespace isaac_teleop::cam_streamer
{

/**
 * Configuration for a single XR plane.
 */
struct XrPlaneConfig
{
    std::string name; // Unique name for this plane
    float distance = 1.0f; // Distance from user in meters
    float width = 1.0f; // Width in meters
    float offset_x = 0.0f; // Horizontal offset (+ = right)
    float offset_y = 0.0f; // Vertical offset (+ = up)
    std::string lock_mode = "lazy"; // "lazy", "world", or "head"
    float look_away_angle = 45.0f;
    float reposition_delay = 0.5f;
    float transition_duration = 0.3f;
    bool is_stereo = false; // True for stereo cameras (left/right)
};

/**
 * Renders multiple camera planes in XR with a SINGLE Vulkan context.
 *
 * This operator solves the multi-context conflict issue by rendering all
 * planes within a single HolovizOp instance and single swapchain pair.
 *
 * Features:
 * - Single Vulkan context for all planes (no VK_ERROR_DEVICE_LOST)
 * - Proper depth compositing between planes
 * - Independent plane positioning and locking modes
 * - Supports mix of stereo and mono cameras
 *
 * Inputs:
 * - xr_frame_state: Frame timing from XrBeginFrameOp
 * - camera_frame_0, camera_frame_0_right: First camera (stereo pair or mono)
 * - camera_frame_1, camera_frame_1_right: Second camera
 * - ... up to camera_frame_N
 *
 * Output:
 * - xr_composition_layer: Single composition layer with all planes rendered
 */
class XrPlaneRendererOp : public holoscan::Operator
{
public:
    HOLOSCAN_OPERATOR_FORWARD_ARGS(XrPlaneRendererOp)

    XrPlaneRendererOp() = default;

    void setup(holoscan::OperatorSpec& spec) override;
    void initialize() override;
    void start() override;
    void stop() override;
    void compute(holoscan::InputContext& input,
                 holoscan::OutputContext& output,
                 holoscan::ExecutionContext& context) override;

    // Set plane configurations (called from Python before initialize)
    void set_plane_configs(const std::vector<XrPlaneConfig>& configs)
    {
        plane_configs_ = configs;
    }

private:
    // Per-plane runtime state
    struct PlaneState
    {
        XrPlaneConfig config;
        size_t input_index = 0;
        std::unique_ptr<CameraPlane> tracker;

        // Camera frame data - left/mono
        holoscan::gxf::Entity entity_left;
        const void* data_left = nullptr;
        int width_left = 0;
        int height_left = 0;

        // Camera frame data - right (stereo only)
        holoscan::gxf::Entity entity_right;
        const void* data_right = nullptr;
        int width_right = 0;
        int height_right = 0;

        // Locked rotation for secondary planes (set when transition completes)
        glm::quat locked_rotation{ 1.f, 0.f, 0.f, 0.f };
        bool rotation_locked = false;

        bool has_data() const
        {
            return data_left != nullptr;
        }
    };

    void render_planes(const std::shared_ptr<holoscan::XrCompositionLayerProjectionStorage>& layer,
                       const glm::vec3& head_pos);

    // Parameters
    holoscan::Parameter<std::shared_ptr<holoscan::XrSession>> xr_session_;
    holoscan::Parameter<bool> verbose_;

    // Plane configs passed from Python (stored separately since Holoscan doesn't support custom structs)
    std::vector<XrPlaneConfig> plane_configs_;

    // Single Vulkan context and swapchains
    holoscan::CudaStreamHandler cuda_stream_handler_;
    holoscan::viz::InstanceHandle holoviz_instance_ = nullptr;
    std::unique_ptr<holoscan::XrSwapchainCuda> color_swapchain_;
    std::unique_ptr<holoscan::XrSwapchainCuda> depth_swapchain_;

    // Plane states (sorted by distance, farthest first for depth rendering)
    std::vector<PlaneState> planes_;

    // Main plane tracker - drives lazy locking for all planes
    std::unique_ptr<CameraPlane> main_tracker_;

    uint64_t frame_count_ = 0;

    // Current frame state
    xr::FrameState current_frame_state_;
    cudaStream_t current_cuda_stream_ = nullptr;
};

} // namespace isaac_teleop::cam_streamer
