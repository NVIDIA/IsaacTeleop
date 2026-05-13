// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <glm/ext/matrix_clip_space.hpp>
#include <glm/ext/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <viz/core/openxr_platform_compat.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/session/xr_backend.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_xr(XrResult r, const char* what)
{
    if (XR_FAILED(r))
    {
        throw std::runtime_error(std::string("XrBackend: ") + what + " failed: XrResult=" + std::to_string(r));
    }
}

void transition_image(VkCommandBuffer cmd,
                      VkImage image,
                      VkImageLayout old_layout,
                      VkImageLayout new_layout,
                      VkAccessFlags src_access,
                      VkAccessFlags dst_access,
                      VkPipelineStageFlags src_stage,
                      VkPipelineStageFlags dst_stage)
{
    VkImageMemoryBarrier b{};
    b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    b.oldLayout = old_layout;
    b.newLayout = new_layout;
    b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    b.subresourceRange.levelCount = 1;
    b.subresourceRange.layerCount = 1;
    b.srcAccessMask = src_access;
    b.dstAccessMask = dst_access;
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &b);
}

} // namespace

XrBackend::XrBackend(Config config) : config_(std::move(config))
{
    // Stage 1: instance + system. VkContext's XR-bound init path reads
    // back instance() + system_id() before stage 2 runs.
    session_ =
        std::make_unique<OpenXrSession>(config_.app_name, config_.extra_xr_extensions, config_.system_wait_seconds);
}

XrBackend::~XrBackend()
{
    destroy();
}

XrInstance XrBackend::xr_instance_handle() const noexcept
{
    return session_ ? session_->instance() : XR_NULL_HANDLE;
}

XrSystemId XrBackend::xr_system_id() const noexcept
{
    return session_ ? session_->system_id() : XR_NULL_SYSTEM_ID;
}

void XrBackend::init(const VkContext& ctx, Resolution /*preferred_size*/)
{
    if (!session_)
    {
        throw std::logic_error("XrBackend::init: OpenXrSession was destroyed");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("XrBackend::init: VkContext is not initialized");
    }
    ctx_ = &ctx;
    try
    {
        session_->attach_graphics(ctx, config_.session_config);
        swapchain_format_ = pick_swapchain_format();
        create_swapchains();
        // Depth submission requires both the extension AND a usable
        // depth format (D32_SFLOAT, matching RenderTarget's depth).
        depth_layer_enabled_ = session_->has_depth_composition_layer();
        if (depth_layer_enabled_)
        {
            depth_swapchain_format_ = pick_depth_swapchain_format();
            depth_layer_enabled_ = depth_swapchain_format_ != 0;
        }
        if (depth_layer_enabled_)
        {
            create_depth_swapchains();
        }
        create_intermediate();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void XrBackend::destroy()
{
    // Balance the frame protocol before teardown — releases any
    // acquired swapchain images and posts an empty xrEndFrame if a
    // begin_frame was in flight. No-op when nothing is pending.
    abort_in_flight_frame();
    // Order: rendering resources → session. Runtime owns swapchain
    // images, so xrDestroySwapchain is enough (no vkDestroyImage).
    render_target_.reset();
    destroy_swapchains();
    session_.reset();
    ctx_ = nullptr;
}

void XrBackend::release_acquired_swapchains() noexcept
{
    auto release_one = [](ViewSwapchain& sw) noexcept
    {
        if (!sw.acquired)
        {
            return;
        }
        XrSwapchainImageReleaseInfo info{ XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
        (void)xrReleaseSwapchainImage(sw.handle, &info);
        sw.acquired = false;
    };
    for (auto& sw : view_swapchains_)
    {
        release_one(sw);
    }
    for (auto& sw : depth_swapchains_)
    {
        release_one(sw);
    }
}

void XrBackend::abort_in_flight_frame() noexcept
{
    // Clear frame_began_ BEFORE end_frame so a throw can't recurse via
    // another abort path. Best-effort: if the runtime rejects this
    // empty endFrame too, swallow — caller is already unwinding.
    if (!frame_began_ || session_ == nullptr)
    {
        return;
    }
    release_acquired_swapchains();
    frame_began_ = false;
    frame_renderable_ = false;
    try
    {
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
    }
    catch (...)
    {
    }
}

void XrBackend::destroy_swapchains()
{
    for (auto& sw : view_swapchains_)
    {
        if (sw.handle != XR_NULL_HANDLE)
        {
            (void)xrDestroySwapchain(sw.handle);
            sw.handle = XR_NULL_HANDLE;
        }
        sw.images.clear();
    }
    view_swapchains_.clear();
    for (auto& sw : depth_swapchains_)
    {
        if (sw.handle != XR_NULL_HANDLE)
        {
            (void)xrDestroySwapchain(sw.handle);
            sw.handle = XR_NULL_HANDLE;
        }
        sw.images.clear();
    }
    depth_swapchains_.clear();
}

int64_t XrBackend::pick_swapchain_format() const
{
    // Prefer sRGB color formats — matches the intermediate RT.
    uint32_t count = 0;
    check_xr(xrEnumerateSwapchainFormats(session_->session(), 0, &count, nullptr), "xrEnumerateSwapchainFormats(count)");
    if (count == 0)
    {
        throw std::runtime_error("XrBackend: runtime reports no supported swapchain formats");
    }
    std::vector<int64_t> formats(count);
    check_xr(xrEnumerateSwapchainFormats(session_->session(), count, &count, formats.data()),
             "xrEnumerateSwapchainFormats(data)");
    // Preference order matches the window swapchain in viz/session/swapchain.cpp.
    constexpr int64_t kPrefs[] = {
        VK_FORMAT_R8G8B8A8_SRGB,
        VK_FORMAT_B8G8R8A8_SRGB,
        VK_FORMAT_R8G8B8A8_UNORM,
        VK_FORMAT_B8G8R8A8_UNORM,
    };
    for (int64_t pref : kPrefs)
    {
        if (std::find(formats.begin(), formats.end(), pref) != formats.end())
        {
            return pref;
        }
    }
    // No preferred format available; take what the runtime offers.
    return formats.front();
}

int64_t XrBackend::pick_depth_swapchain_format() const
{
    // Must match RenderTarget::depth_format(): vkCmdCopyImage requires
    // identical formats for depth (no blit fallback for D/S). Returning
    // 0 disables depth submission.
    uint32_t count = 0;
    if (xrEnumerateSwapchainFormats(session_->session(), 0, &count, nullptr) != XR_SUCCESS || count == 0)
    {
        return 0;
    }
    std::vector<int64_t> formats(count);
    if (xrEnumerateSwapchainFormats(session_->session(), count, &count, formats.data()) != XR_SUCCESS)
    {
        return 0;
    }
    if (std::find(formats.begin(), formats.end(), static_cast<int64_t>(VK_FORMAT_D32_SFLOAT)) != formats.end())
    {
        return VK_FORMAT_D32_SFLOAT;
    }
    return 0;
}

void XrBackend::create_depth_swapchains()
{
    const auto& views = session_->view_configuration_views();
    depth_swapchains_.assign(views.size(), ViewSwapchain{});
    for (size_t i = 0; i < views.size(); ++i)
    {
        XrSwapchainCreateInfo info{ XR_TYPE_SWAPCHAIN_CREATE_INFO };
        info.usageFlags = XR_SWAPCHAIN_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
        info.format = depth_swapchain_format_;
        info.sampleCount = 1;
        info.width = views[i].recommendedImageRectWidth;
        info.height = views[i].recommendedImageRectHeight;
        info.faceCount = 1;
        info.arraySize = 1;
        info.mipCount = 1;
        check_xr(xrCreateSwapchain(session_->session(), &info, &depth_swapchains_[i].handle), "xrCreateSwapchain(depth)");
        depth_swapchains_[i].width = info.width;
        depth_swapchains_[i].height = info.height;

        uint32_t img_count = 0;
        check_xr(xrEnumerateSwapchainImages(depth_swapchains_[i].handle, 0, &img_count, nullptr),
                 "xrEnumerateSwapchainImages(depth count)");
        std::vector<XrSwapchainImageVulkan2KHR> vk_images(
            img_count, XrSwapchainImageVulkan2KHR{ XR_TYPE_SWAPCHAIN_IMAGE_VULKAN2_KHR });
        check_xr(xrEnumerateSwapchainImages(depth_swapchains_[i].handle, img_count, &img_count,
                                            reinterpret_cast<XrSwapchainImageBaseHeader*>(vk_images.data())),
                 "xrEnumerateSwapchainImages(depth data)");
        depth_swapchains_[i].images.reserve(img_count);
        for (const auto& vi : vk_images)
        {
            depth_swapchains_[i].images.push_back(vi.image);
        }
    }
}

void XrBackend::create_swapchains()
{
    const auto& views = session_->view_configuration_views();
    view_swapchains_.assign(views.size(), ViewSwapchain{});

    for (size_t i = 0; i < views.size(); ++i)
    {
        XrSwapchainCreateInfo info{ XR_TYPE_SWAPCHAIN_CREATE_INFO };
        info.usageFlags = XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT | XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT;
        info.format = swapchain_format_;
        info.sampleCount = 1;
        info.width = views[i].recommendedImageRectWidth;
        info.height = views[i].recommendedImageRectHeight;
        info.faceCount = 1;
        info.arraySize = 1;
        info.mipCount = 1;
        check_xr(xrCreateSwapchain(session_->session(), &info, &view_swapchains_[i].handle), "xrCreateSwapchain");
        view_swapchains_[i].width = info.width;
        view_swapchains_[i].height = info.height;

        uint32_t img_count = 0;
        check_xr(xrEnumerateSwapchainImages(view_swapchains_[i].handle, 0, &img_count, nullptr),
                 "xrEnumerateSwapchainImages(count)");
        std::vector<XrSwapchainImageVulkan2KHR> vk_images(
            img_count, XrSwapchainImageVulkan2KHR{ XR_TYPE_SWAPCHAIN_IMAGE_VULKAN2_KHR });
        check_xr(xrEnumerateSwapchainImages(view_swapchains_[i].handle, img_count, &img_count,
                                            reinterpret_cast<XrSwapchainImageBaseHeader*>(vk_images.data())),
                 "xrEnumerateSwapchainImages(data)");
        view_swapchains_[i].images.reserve(img_count);
        for (const auto& vi : vk_images)
        {
            view_swapchains_[i].images.push_back(vi.image);
        }
    }
}

void XrBackend::create_intermediate()
{
    // Wide side-by-side intermediate (sum of per-view widths × max height).
    // Layers iterate frame.views, each rendering into its assigned x-offset
    // region; record_post_render_pass blits each region to its eye's
    // swapchain image.
    const auto& views = session_->view_configuration_views();
    uint32_t total_w = 0;
    uint32_t max_h = 0;
    for (const auto& v : views)
    {
        total_w += v.recommendedImageRectWidth;
        max_h = std::max(max_h, v.recommendedImageRectHeight);
    }
    RenderTarget::Config rt_cfg{};
    rt_cfg.resolution = Resolution{ total_w, max_h };
    render_target_ = RenderTarget::create(*ctx_, rt_cfg);
}

namespace
{
// XrPosef → eye-to-world matrix. Inverse is the view matrix.
glm::mat4 pose_to_world_matrix(const XrPosef& pose)
{
    const glm::quat q(pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z);
    const glm::vec3 p(pose.position.x, pose.position.y, pose.position.z);
    return glm::translate(glm::mat4(1.0f), p) * glm::mat4_cast(q);
}

// Per-eye projection from XR's signed-angle FOV. frustumRH_ZO gives
// right-handed view + [0,1] depth (Vulkan). top/bottom are swapped
// (angleUp → bottom) so XR-world +Y maps to Vulkan-clip −Y.
glm::mat4 fov_to_projection_matrix(const XrFovf& fov, float near_z, float far_z)
{
    const float left = near_z * std::tan(fov.angleLeft);
    const float right = near_z * std::tan(fov.angleRight);
    const float bottom = near_z * std::tan(fov.angleUp);
    const float top = near_z * std::tan(fov.angleDown);
    return glm::frustumRH_ZO(left, right, bottom, top, near_z, far_z);
}

} // namespace

std::optional<DisplayBackend::Frame> XrBackend::begin_frame(int64_t /*ignored*/)
{
    if (!session_)
    {
        return std::nullopt;
    }
    session_->poll_events();
    if (!session_->session_running() || session_->exit_requested())
    {
        return std::nullopt;
    }
    last_frame_state_ = XrFrameState{ XR_TYPE_FRAME_STATE };
    if (!session_->wait_frame(&last_frame_state_))
    {
        return std::nullopt;
    }
    session_->begin_frame();
    frame_began_ = true;
    frame_renderable_ = false;

    // From here on, an exception MUST balance xrBeginFrame with an
    // empty xrEndFrame and release any swapchains we acquired. The
    // compositor's outer FrameGuard only exists once we return a Frame,
    // so until then this local guard owns the protocol balance.
    // Dismiss right before returning the frame.
    struct InFlightGuard
    {
        XrBackend* self;
        bool dismissed = false;
        ~InFlightGuard()
        {
            if (!dismissed && self != nullptr)
            {
                self->abort_in_flight_frame();
            }
        }
    } in_flight_guard{ this };

    // Skip-path xrEndFrame: clear flags + dismiss guard BEFORE the call so
    // a throw propagates cleanly without abort_in_flight_frame retrying on
    // a session that just rejected the first attempt. Matches the main
    // end_frame ordering.
    auto submit_empty_end_frame = [&]()
    {
        frame_began_ = false;
        in_flight_guard.dismissed = true;
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
    };

    if (!last_frame_state_.shouldRender)
    {
        // Runtime asks us to skip rendering (headset blacked out, app
        // not focused). Empty xrEndFrame to balance xrBeginFrame.
        submit_empty_end_frame();
        return std::nullopt;
    }

    if (!session_->locate_views(last_frame_state_.predictedDisplayTime, &last_view_state_, &last_views_))
    {
        // Tracking lost; submit empty frame to balance.
        submit_empty_end_frame();
        return std::nullopt;
    }

    // Locate the VIEW reference space — head pose at predicted_display_time.
    // Optional from a rendering standpoint (per-eye matrices already in
    // last_views_), but exposed via Frame::head_pose for layers / apps
    // doing head-locked placement. Tracking-loss returns false; the
    // method itself doesn't throw on XR_FAILED.
    XrSpaceLocation head_loc{ XR_TYPE_SPACE_LOCATION };
    const bool head_ok = session_->locate_view_space(last_frame_state_.predictedDisplayTime, &head_loc);

    // Acquire+wait per swapchain (color + optional depth). `acquired`
    // is set immediately after acquire (not wait) — the spec requires
    // every acquire to be released regardless of wait outcome, so a
    // throwing wait must still surface to the cleanup pass.
    auto acquire_pair = [](ViewSwapchain& sw, const char* what_a, const char* what_w)
    {
        XrSwapchainImageAcquireInfo acquire_info{ XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO };
        check_xr(xrAcquireSwapchainImage(sw.handle, &acquire_info, &sw.current_image_index), what_a);
        sw.acquired = true;
        XrSwapchainImageWaitInfo wait_info{ XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO };
        wait_info.timeout = XR_INFINITE_DURATION;
        check_xr(xrWaitSwapchainImage(sw.handle, &wait_info), what_w);
    };
    for (auto& sw : view_swapchains_)
    {
        acquire_pair(sw, "xrAcquireSwapchainImage(color)", "xrWaitSwapchainImage(color)");
    }
    for (auto& sw : depth_swapchains_)
    {
        acquire_pair(sw, "xrAcquireSwapchainImage(depth)", "xrWaitSwapchainImage(depth)");
    }
    frame_renderable_ = true;

    // Per-eye ViewInfo: each gets its own region of the wide
    // intermediate (x_offset accumulates) plus view+proj matrices.
    const auto& view_cfgs = session_->view_configuration_views();
    Frame f{};
    f.views.assign(view_swapchains_.size(), ViewInfo{});
    int32_t x_offset = 0;
    for (size_t i = 0; i < view_swapchains_.size(); ++i)
    {
        const auto& vc = view_cfgs[i];
        const XrView& xv = last_views_[i];
        ViewInfo& vi = f.views[i];
        vi.viewport = Rect2D{ x_offset, 0, vc.recommendedImageRectWidth, vc.recommendedImageRectHeight };
        vi.view_matrix = glm::inverse(pose_to_world_matrix(xv.pose));
        vi.projection_matrix = fov_to_projection_matrix(xv.fov, session_->near_z(), session_->far_z());
        vi.fov = Fov{ xv.fov.angleLeft, xv.fov.angleRight, xv.fov.angleUp, xv.fov.angleDown };
        vi.pose = Pose3D{
            glm::vec3(xv.pose.position.x, xv.pose.position.y, xv.pose.position.z),
            glm::quat(xv.pose.orientation.w, xv.pose.orientation.x, xv.pose.orientation.y, xv.pose.orientation.z),
        };
        x_offset += static_cast<int32_t>(vc.recommendedImageRectWidth);
    }
    if (head_ok)
    {
        f.head_pose = Pose3D{
            glm::vec3(head_loc.pose.position.x, head_loc.pose.position.y, head_loc.pose.position.z),
            glm::quat(head_loc.pose.orientation.w, head_loc.pose.orientation.x, head_loc.pose.orientation.y,
                      head_loc.pose.orientation.z),
        };
    }
    f.wait_before_render = VK_NULL_HANDLE;
    f.signal_after_render = VK_NULL_HANDLE;
    f.backend_token = static_cast<uint64_t>(last_frame_state_.predictedDisplayTime);
    // Hand protocol-balance off to the compositor's FrameGuard.
    in_flight_guard.dismissed = true;
    return f;
}

const RenderTarget& XrBackend::render_target() const
{
    if (!render_target_)
    {
        throw std::runtime_error("XrBackend::render_target: backend not initialized");
    }
    return *render_target_;
}

namespace
{
// transition_image variant with an explicit aspect mask (the file-scope
// helper hardcodes COLOR_BIT).
void transition_image_aspect(VkCommandBuffer cmd,
                             VkImage image,
                             VkImageAspectFlags aspect,
                             VkImageLayout old_layout,
                             VkImageLayout new_layout,
                             VkAccessFlags src_access,
                             VkAccessFlags dst_access,
                             VkPipelineStageFlags src_stage,
                             VkPipelineStageFlags dst_stage)
{
    VkImageMemoryBarrier b{};
    b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    b.oldLayout = old_layout;
    b.newLayout = new_layout;
    b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange.aspectMask = aspect;
    b.subresourceRange.levelCount = 1;
    b.subresourceRange.layerCount = 1;
    b.srcAccessMask = src_access;
    b.dstAccessMask = dst_access;
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &b);
}
} // namespace

void XrBackend::record_post_render_pass(VkCommandBuffer cmd, const Frame& frame)
{
    if (!frame_renderable_ || !render_target_)
    {
        return;
    }
    const VkImage src = render_target_->color_image();

    // Wide intermediate split-blit: each per-eye region of the source
    // (left half → eye 0, right half → eye 1, ...) goes to its own
    // swapchain image. The src rect comes from frame.views[i].viewport
    // — same offsets QuadLayer used to render into per-eye regions.
    // RT is in TRANSFER_SRC_OPTIMAL after the render pass's final
    // layout. Each XR swapchain image arrives in an unspecified
    // layout, so we transition UNDEFINED → TRANSFER_DST → COLOR_ATTACHMENT.
    for (size_t i = 0; i < view_swapchains_.size(); ++i)
    {
        const auto& sw = view_swapchains_[i];
        const VkImage dst = sw.images[sw.current_image_index];
        const Rect2D src_rect = (i < frame.views.size()) ? frame.views[i].viewport : Rect2D{ 0, 0, sw.width, sw.height };

        transition_image(cmd, dst, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
                         VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);

        VkImageBlit region{};
        region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.srcSubresource.layerCount = 1;
        region.srcOffsets[0] = { src_rect.x, src_rect.y, 0 };
        region.srcOffsets[1] = { src_rect.x + static_cast<int32_t>(src_rect.width),
                                 src_rect.y + static_cast<int32_t>(src_rect.height), 1 };
        region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.dstSubresource.layerCount = 1;
        region.dstOffsets[1] = { static_cast<int32_t>(sw.width), static_cast<int32_t>(sw.height), 1 };
        vkCmdBlitImage(cmd, src, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1,
                       &region, VK_FILTER_LINEAR);

        // OpenXR expects COLOR_ATTACHMENT_OPTIMAL at xrEndFrame.
        transition_image(cmd, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                         VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_COLOR_ATTACHMENT_READ_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT);
    }

    // Per-eye depth copy for XR_KHR_composition_layer_depth. Copy not
    // blit — depth/stencil isn't blittable; src/dst formats are forced
    // identical via pick_depth_swapchain_format.
    if (depth_layer_enabled_)
    {
        const VkImage depth_src = render_target_->depth_image();
        for (size_t i = 0; i < depth_swapchains_.size(); ++i)
        {
            const auto& sw = depth_swapchains_[i];
            const VkImage dst = sw.images[sw.current_image_index];
            const Rect2D src_rect =
                (i < frame.views.size()) ? frame.views[i].viewport : Rect2D{ 0, 0, sw.width, sw.height };

            transition_image_aspect(cmd, dst, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_UNDEFINED,
                                    VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT,
                                    VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);

            VkImageCopy region{};
            region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
            region.srcSubresource.layerCount = 1;
            region.srcOffset = { src_rect.x, src_rect.y, 0 };
            region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
            region.dstSubresource.layerCount = 1;
            region.dstOffset = { 0, 0, 0 };
            region.extent = { sw.width, sw.height, 1 };
            vkCmdCopyImage(cmd, depth_src, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst,
                           VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

            // DEPTH_STENCIL_READ_ONLY is the conventional "runtime
            // samples this" layout for the depth-info subImage.
            transition_image_aspect(cmd, dst, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                                    VK_IMAGE_LAYOUT_DEPTH_STENCIL_READ_ONLY_OPTIMAL, VK_ACCESS_TRANSFER_WRITE_BIT,
                                    VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                                    VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
        }
    }
}

void XrBackend::end_frame(const Frame& /*frame*/)
{
    if (!frame_began_)
    {
        return;
    }
    if (!frame_renderable_)
    {
        // begin_frame already submitted xrEndFrame on the skip path.
        frame_began_ = false;
        return;
    }

    // Release acquired swapchains. Clear `acquired` AFTER release —
    // if release throws, abort_frame's pass needs to see them flagged
    // and retry.
    for (auto& sw : view_swapchains_)
    {
        if (!sw.acquired)
        {
            continue;
        }
        XrSwapchainImageReleaseInfo release_info{ XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
        check_xr(xrReleaseSwapchainImage(sw.handle, &release_info), "xrReleaseSwapchainImage");
        sw.acquired = false;
    }
    for (auto& sw : depth_swapchains_)
    {
        if (!sw.acquired)
        {
            continue;
        }
        XrSwapchainImageReleaseInfo release_info{ XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
        check_xr(xrReleaseSwapchainImage(sw.handle, &release_info), "xrReleaseSwapchainImage(depth)");
        sw.acquired = false;
    }

    // Per-eye depth_info, chained via .next on each ProjectionView.
    // Storage outlives xrEndFrame. nearZ/farZ MUST match the projection
    // matrix; runtime uses them to reconstruct world-space depth.
    std::vector<XrCompositionLayerDepthInfoKHR> depth_infos;
    if (depth_layer_enabled_)
    {
        depth_infos.assign(
            depth_swapchains_.size(), XrCompositionLayerDepthInfoKHR{ XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR });
        for (size_t i = 0; i < depth_swapchains_.size(); ++i)
        {
            depth_infos[i].subImage.swapchain = depth_swapchains_[i].handle;
            depth_infos[i].subImage.imageRect.offset = { 0, 0 };
            depth_infos[i].subImage.imageRect.extent = { static_cast<int32_t>(depth_swapchains_[i].width),
                                                         static_cast<int32_t>(depth_swapchains_[i].height) };
            depth_infos[i].subImage.imageArrayIndex = 0;
            depth_infos[i].minDepth = 0.0f;
            depth_infos[i].maxDepth = 1.0f;
            depth_infos[i].nearZ = session_->near_z();
            depth_infos[i].farZ = session_->far_z();
        }
    }

    // Per-eye projection views referencing their own swapchain at the
    // full recommended rect.
    std::vector<XrCompositionLayerProjectionView> proj_views(
        view_swapchains_.size(), XrCompositionLayerProjectionView{ XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW });
    for (size_t i = 0; i < view_swapchains_.size(); ++i)
    {
        proj_views[i].pose = last_views_[i].pose;
        proj_views[i].fov = last_views_[i].fov;
        proj_views[i].subImage.swapchain = view_swapchains_[i].handle;
        proj_views[i].subImage.imageRect.offset = { 0, 0 };
        proj_views[i].subImage.imageRect.extent = { static_cast<int32_t>(view_swapchains_[i].width),
                                                    static_cast<int32_t>(view_swapchains_[i].height) };
        proj_views[i].subImage.imageArrayIndex = 0;
        if (depth_layer_enabled_ && i < depth_infos.size())
        {
            proj_views[i].next = &depth_infos[i];
        }
    }

    XrCompositionLayerProjection projection_layer{ XR_TYPE_COMPOSITION_LAYER_PROJECTION };
    // Non-opaque env modes need the alpha-blend layer flag for the
    // runtime to honor our alpha channel. Straight alpha (not premul).
    const bool is_passthrough = session_->environment_blend_mode() != XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    projection_layer.layerFlags = is_passthrough ? XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT : 0;
    projection_layer.space = session_->reference_space();
    projection_layer.viewCount = static_cast<uint32_t>(proj_views.size());
    projection_layer.views = proj_views.data();

    const std::vector<const XrCompositionLayerBaseHeader*> layers = {
        reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection_layer),
    };
    // Clear flags BEFORE end_frame so a throw doesn't trigger a second
    // xrEndFrame from the compositor's FrameGuard → abort_frame path.
    frame_began_ = false;
    frame_renderable_ = false;
    session_->end_frame(last_frame_state_.predictedDisplayTime, layers);
}

void XrBackend::abort_frame(const Frame& /*frame*/)
{
    // Idempotent — no-op if the in-flight guard already aborted.
    abort_in_flight_frame();
}

void XrBackend::poll_events()
{
    if (session_)
    {
        session_->poll_events();
    }
}

bool XrBackend::should_close() const
{
    return session_ ? session_->exit_requested() : false;
}

Resolution XrBackend::current_extent() const
{
    return render_target_ ? render_target_->resolution() : Resolution{};
}

uint32_t XrBackend::image_count() const
{
    // M5 stub: XR is single-frame-in-flight until the per-XR-swapchain
    // fence mapping is wired up (TODO when M5 lands). Returns 1 so the
    // compositor allocates one fence and falls back to the original
    // single-frame-in-flight behavior for this backend.
    return 1;
}

XrBackend::OxrHandles XrBackend::oxr_handles() const noexcept
{
    OxrHandles h{};
    if (session_)
    {
        h.instance = session_->instance();
        h.session = session_->session();
        h.reference_space = session_->reference_space();
        h.view_space = session_->view_space();
        // Loader-level entry, statically linked.
        h.xrGetInstanceProcAddr = ::xrGetInstanceProcAddr;
    }
    return h;
}

} // namespace viz
