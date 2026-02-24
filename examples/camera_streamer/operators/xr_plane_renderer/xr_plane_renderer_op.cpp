// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

#include "xr_plane_renderer_op.hpp"

#include "glm/ext/matrix_clip_space.hpp"
#include "glm/ext/matrix_transform.hpp"
#include "glm/gtc/quaternion.hpp"
#include "glm/gtc/type_ptr.hpp"
#include "glm/gtx/quaternion.hpp"

#include <algorithm>
#include <cuda_runtime.h>

namespace isaac_teleop::cam_streamer
{

namespace
{

// Get forward direction (-Z in OpenXR) from head orientation.
glm::vec3 get_forward(const xr::Quaternionf& orientation)
{
    glm::quat q(orientation.w, orientation.x, orientation.y, orientation.z);
    return q * glm::vec3(0.f, 0.f, -1.f);
}

// Convert xr::Vector3f to glm::vec3.
glm::vec3 to_glm(const xr::Vector3f& v)
{
    return glm::vec3(v.x, v.y, v.z);
}

// Convert xr::Quaternionf to glm::quat.
glm::quat to_glm(const xr::Quaternionf& q)
{
    return glm::quat(q.w, q.x, q.y, q.z);
}

// Project forward direction onto XZ plane (horizontal).
glm::vec3 project_to_xz(const glm::vec3& forward)
{
    glm::vec3 forward_xz(forward.x, 0.f, forward.z);
    float len = glm::length(forward_xz);
    if (len > 0.001f)
    {
        return forward_xz / len;
    }
    return glm::vec3(0.f, 0.f, -1.f);
}

LockMode parse_lock_mode(const std::string& mode_str)
{
    if (mode_str == "world")
    {
        return LockMode::World;
    }
    else if (mode_str == "head")
    {
        return LockMode::Head;
    }
    return LockMode::Lazy; // Default
}

} // namespace

void XrPlaneRendererOp::setup(holoscan::OperatorSpec& spec)
{
    spec.input<xr::FrameState>("xr_frame_state").condition(holoscan::ConditionType::kMessageAvailable);

    // Dynamic camera inputs - up to 8 planes (16 inputs for stereo)
    for (int i = 0; i < 8; i++)
    {
        std::string name_left = "camera_frame_" + std::to_string(i);
        std::string name_right = "camera_frame_" + std::to_string(i) + "_right";

        spec.input<holoscan::gxf::Entity>(name_left, holoscan::IOSpec::IOSize(1), holoscan::IOSpec::QueuePolicy::kPop)
            .condition(holoscan::ConditionType::kNone);
        spec.input<holoscan::gxf::Entity>(name_right, holoscan::IOSpec::IOSize(1), holoscan::IOSpec::QueuePolicy::kPop)
            .condition(holoscan::ConditionType::kNone);
    }

    spec.output<std::shared_ptr<xr::CompositionLayerBaseHeader>>("xr_composition_layer");

    // Parameters (plane configs are set via set_plane_configs() before initialize)
    spec.param(xr_session_, "xr_session", "XR Session", "OpenXR session");
    spec.param(verbose_, "verbose", "Verbose", "Enable verbose logging", false);

    cuda_stream_handler_.define_params(spec);
}

void XrPlaneRendererOp::initialize()
{
    Operator::initialize();

    // Use plane configs set via set_plane_configs()
    if (plane_configs_.empty())
    {
        HOLOSCAN_LOG_ERROR("XrPlaneRendererOp: No planes configured. Call set_plane_configs() first.");
        return;
    }

    // Build plane states from configs
    planes_.resize(plane_configs_.size());
    for (size_t i = 0; i < plane_configs_.size(); i++)
    {
        planes_[i].config = plane_configs_[i];
    }

    // Sort planes by distance (farthest first) for proper depth rendering
    std::sort(planes_.begin(), planes_.end(),
              [](const PlaneState& a, const PlaneState& b) { return a.config.distance > b.config.distance; });

    if (verbose_.get())
    {
        HOLOSCAN_LOG_INFO("XrPlaneRendererOp: {} planes configured", planes_.size());
        for (const auto& plane : planes_)
        {
            HOLOSCAN_LOG_INFO("  - {}: distance={}m, width={}m, offset=({}, {})m, stereo={}", plane.config.name,
                              plane.config.distance, plane.config.width, plane.config.offset_x, plane.config.offset_y,
                              plane.config.is_stereo ? "true" : "false");
        }
    }
}

void XrPlaneRendererOp::start()
{
    auto xr_session = xr_session_.get();
    uint32_t width =
        xr_session->view_configurations()[0].recommendedImageRectWidth * xr_session->view_configurations().size();
    uint32_t height = xr_session->view_configurations()[0].recommendedImageRectHeight;

    holoviz_instance_ = holoscan::viz::Create();
    holoscan::viz::SetCurrent(holoviz_instance_);
    holoscan::viz::Init(width, height, "XR Multi Plane", holoscan::viz::InitFlags::HEADLESS);

    color_swapchain_ = std::make_unique<holoscan::XrSwapchainCuda>(
        *xr_session, holoscan::XrSwapchainCuda::Format::R8G8B8A8_SRGB, width, height);
    depth_swapchain_ = std::make_unique<holoscan::XrSwapchainCuda>(
        *xr_session, holoscan::XrSwapchainCuda::Format::D32_SFLOAT, width, height);

    // Initialize the main tracker - this drives lazy locking for all planes
    // The main plane is the first one in the config (usually head camera)
    if (!planes_.empty())
    {
        auto& main_plane = planes_[0];
        CameraPlaneConfig config;
        config.lock_mode = parse_lock_mode(main_plane.config.lock_mode);
        config.distance = main_plane.config.distance;
        config.width = main_plane.config.width;
        config.offset_x = 0.0f; // Main plane has no offset
        config.offset_y = 0.0f;
        config.look_away_angle = main_plane.config.look_away_angle;
        config.reposition_delay = main_plane.config.reposition_delay;
        config.transition_duration = main_plane.config.transition_duration;
        main_tracker_ = std::make_unique<CameraPlane>(config);
    }

    if (verbose_.get())
    {
        HOLOSCAN_LOG_INFO("XrPlaneRendererOp started: {}x{}, {} planes", width, height, planes_.size());
    }
}

void XrPlaneRendererOp::stop()
{
    for (auto& plane : planes_)
    {
        plane.entity_left = holoscan::gxf::Entity();
        plane.entity_right = holoscan::gxf::Entity();
        plane.data_left = nullptr;
        plane.data_right = nullptr;
    }
    main_tracker_.reset();

    holoscan::viz::Shutdown(holoviz_instance_);
    holoviz_instance_ = nullptr;

    if (verbose_.get())
    {
        HOLOSCAN_LOG_INFO("XrPlaneRendererOp stopped. Frames: {}", frame_count_);
    }
}

void XrPlaneRendererOp::compute(holoscan::InputContext& input,
                                holoscan::OutputContext& output,
                                holoscan::ExecutionContext& context)
{
    auto xr_session = xr_session_.get();
    auto frame_state = input.receive<xr::FrameState>("xr_frame_state");
    current_frame_state_ = *frame_state;

    // Update camera frames for each plane
    for (size_t i = 0; i < planes_.size(); i++)
    {
        auto& plane = planes_[i];
        std::string input_left = "camera_frame_" + std::to_string(i);
        std::string input_right = "camera_frame_" + std::to_string(i) + "_right";

        // Update left/mono frame
        if (!input.empty(input_left.c_str()))
        {
            auto entity = input.receive<holoscan::gxf::Entity>(input_left.c_str());
            if (entity)
            {
                auto& gxf_entity = static_cast<nvidia::gxf::Entity&>(entity.value());
                auto tensor = gxf_entity.get<nvidia::gxf::Tensor>();
                if (tensor)
                {
                    plane.entity_left = entity.value();
                    plane.data_left = tensor.value()->pointer();
                    plane.width_left = tensor.value()->shape().dimension(1);
                    plane.height_left = tensor.value()->shape().dimension(0);
                }
            }
        }

        // Update right frame (stereo mode)
        if (plane.config.is_stereo && !input.empty(input_right.c_str()))
        {
            auto entity = input.receive<holoscan::gxf::Entity>(input_right.c_str());
            if (entity)
            {
                auto& gxf_entity = static_cast<nvidia::gxf::Entity&>(entity.value());
                auto tensor = gxf_entity.get<nvidia::gxf::Tensor>();
                if (tensor)
                {
                    plane.entity_right = entity.value();
                    plane.data_right = tensor.value()->pointer();
                    plane.width_right = tensor.value()->shape().dimension(1);
                    plane.height_right = tensor.value()->shape().dimension(0);
                }
            }
        }
    }

    // Check if any plane has data
    bool has_any_data = false;
    for (const auto& plane : planes_)
    {
        if (plane.has_data())
        {
            has_any_data = true;
            break;
        }
    }

    if (!has_any_data)
    {
        output.emit(std::shared_ptr<xr::CompositionLayerBaseHeader>(nullptr), "xr_composition_layer");
        return;
    }

    // Get head pose and update main tracker only
    // Secondary planes will be positioned relative to the main plane
    xr::Space reference_space = xr_session->reference_space();
    xr::SpaceLocation head_location =
        xr_session->view_space().locateSpace(reference_space, frame_state->predictedDisplayTime);

    glm::vec3 head_pos = to_glm(head_location.pose.position);
    glm::quat head_orientation = to_glm(head_location.pose.orientation);
    glm::vec3 forward_xz = project_to_xz(get_forward(head_location.pose.orientation));

    if (main_tracker_)
    {
        main_tracker_->update(head_pos, head_orientation, forward_xz);
    }

    // Create composition layer
    auto composition_layer = holoscan::XrCompositionLayerProjectionStorage::create_for_frame(
        *frame_state, *xr_session, *color_swapchain_, *depth_swapchain_);

    auto color_tensor = color_swapchain_->acquire();
    auto depth_tensor = depth_swapchain_->acquire();
    current_cuda_stream_ = cuda_stream_handler_.get_cuda_stream(context.context());

    holoscan::viz::SetCurrent(holoviz_instance_);
    holoscan::viz::SetCudaStream(current_cuda_stream_);

    // Render all planes within a singlerender pass
    render_planes(composition_layer, head_pos);

    // Read back the framebuffer
    holoscan::viz::ReadFramebuffer(holoscan::viz::ImageFormat::R8G8B8A8_UNORM, color_swapchain_->width(),
                                   color_swapchain_->height(), color_tensor.nbytes(),
                                   reinterpret_cast<CUdeviceptr>(color_tensor.data()));
    holoscan::viz::ReadFramebuffer(holoscan::viz::ImageFormat::D32_SFLOAT, depth_swapchain_->width(),
                                   depth_swapchain_->height(), depth_tensor.nbytes(),
                                   reinterpret_cast<CUdeviceptr>(depth_tensor.data()));

    color_swapchain_->release(current_cuda_stream_);
    depth_swapchain_->release(current_cuda_stream_);

    frame_count_++;
    output.emit(std::static_pointer_cast<xr::CompositionLayerBaseHeader>(composition_layer), "xr_composition_layer");
}

void XrPlaneRendererOp::render_planes(const std::shared_ptr<holoscan::XrCompositionLayerProjectionStorage>& layer,
                                      const glm::vec3& head_pos)
{

    if (!main_tracker_)
        return;

    // Get main plane position and rotation - this drives all planes
    glm::vec3 main_pos = main_tracker_->position();
    glm::quat main_rotation = main_tracker_->rotation();

    // Render all planes for all eyes in a single Begin/End block
    holoscan::viz::Begin();

    // Render all planes (sorted by distance, farthest first)
    for (size_t plane_idx = 0; plane_idx < planes_.size(); plane_idx++)
    {
        auto& plane = planes_[plane_idx];
        if (!plane.has_data())
            continue;

        // Compute plane position relative to main plane
        glm::vec3 plane_pos;
        glm::quat plane_rotation;

        if (plane_idx == 0)
        {
            // Main plane - use main tracker position and rotation directly
            plane_pos = main_pos;
            plane_rotation = main_rotation;
        }
        else
        {
            // Secondary plane - positioned relative to the main plane
            // This ensures secondary planes stay anchored when main plane is lazy-locked

            // Get forward/right/up directions from main plane's orientation
            glm::vec3 forward = main_rotation * glm::vec3(0.0f, 0.0f, -1.0f);
            glm::vec3 right = main_rotation * glm::vec3(1.0f, 0.0f, 0.0f);
            glm::vec3 up = glm::vec3(0.0f, 1.0f, 0.0f); // World up

            // Offset from main plane position:
            // - Forward: difference in distance from main plane's distance
            // - Right/Up: configured offsets
            float main_distance = planes_[0].config.distance;
            float distance_offset = plane.config.distance - main_distance;

            plane_pos = main_pos + forward * distance_offset + right * plane.config.offset_x + up * plane.config.offset_y;

            // Handle rotation based on transition state:
            // - During transition: face the user (compute dynamically)
            // - After transition: use locked rotation
            if (main_tracker_->is_transitioning())
            {
                // Transitioning - compute rotation to face user
                plane.rotation_locked = false;

                glm::vec3 to_head = head_pos - plane_pos;
                to_head.y = 0.0f; // Project to horizontal plane
                float len = glm::length(to_head);
                if (len > 0.001f)
                {
                    to_head /= len;
                    float yaw = std::atan2(-to_head.x, -to_head.z);
                    plane_rotation = glm::angleAxis(yaw, glm::vec3(0.0f, 1.0f, 0.0f));
                }
                else
                {
                    plane_rotation = main_rotation;
                }
            }
            else
            {
                // Not transitioning - lock/use locked rotation
                if (!plane.rotation_locked)
                {
                    // Just finished transitioning - lock current facing rotation
                    glm::vec3 to_head = head_pos - plane_pos;
                    to_head.y = 0.0f;
                    float len = glm::length(to_head);
                    if (len > 0.001f)
                    {
                        to_head /= len;
                        float yaw = std::atan2(-to_head.x, -to_head.z);
                        plane.locked_rotation = glm::angleAxis(yaw, glm::vec3(0.0f, 1.0f, 0.0f));
                    }
                    else
                    {
                        plane.locked_rotation = main_rotation;
                    }
                    plane.rotation_locked = true;
                }
                plane_rotation = plane.locked_rotation;
            }
        }

        // Render this plane for each eye
        const void* frame_data = plane.data_left;
        int frame_width = plane.width_left;
        int frame_height = plane.height_left;

        if (!frame_data)
            continue;

        for (int eye_idx = 0; eye_idx < layer->viewCount; eye_idx++)
        {
            auto& view = layer->views[eye_idx];

            float aspect = static_cast<float>(frame_height) / static_cast<float>(frame_width);

            holoscan::viz::BeginImageLayer();

            holoscan::viz::ImageCudaDevice(frame_width, frame_height, holoscan::viz::ImageFormat::R8G8B8_UNORM,
                                           reinterpret_cast<CUdeviceptr>(frame_data));

            // Compute MVP for this plane and eye
            glm::mat4 model = glm::translate(glm::mat4{ 1 }, plane_pos);
            model = model * glm::mat4_cast(plane_rotation);
            model = glm::scale(model, glm::vec3(plane.config.width, -plane.config.width * aspect, 1.f));

            glm::mat4 view_rot = glm::mat4_cast(glm::make_quat(&view.pose.orientation.x));
            glm::mat4 view_trans = glm::translate(glm::mat4{ 1 }, glm::make_vec3(&view.pose.position.x));
            glm::mat4 view_mat = glm::inverse(view_trans * view_rot);

            glm::mat4 proj = glm::frustumRH_ZO(layer->depth_info[eye_idx].nearZ * glm::tan(view.fov.angleLeft),
                                               layer->depth_info[eye_idx].nearZ * glm::tan(view.fov.angleRight),
                                               layer->depth_info[eye_idx].nearZ * glm::tan(view.fov.angleUp),
                                               layer->depth_info[eye_idx].nearZ * glm::tan(view.fov.angleDown),
                                               layer->depth_info[eye_idx].nearZ, layer->depth_info[eye_idx].farZ);

            glm::mat4 mvp = glm::transpose(proj * view_mat * model);

            // Add view for just this eye's region
            holoscan::viz::LayerAddView(
                static_cast<float>(view.subImage.imageRect.offset.x) / color_swapchain_->width(),
                static_cast<float>(view.subImage.imageRect.offset.y) / color_swapchain_->height(),
                static_cast<float>(view.subImage.imageRect.extent.width) / color_swapchain_->width(),
                static_cast<float>(view.subImage.imageRect.extent.height) / color_swapchain_->height(),
                glm::value_ptr(mvp));

            holoscan::viz::EndLayer();
        }
    }

    holoscan::viz::End();
}

} // namespace isaac_teleop::cam_streamer
