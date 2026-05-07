// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/xr_backend.hpp>
#include <viz/xr/openxr_instance.hpp>

#define XR_USE_GRAPHICS_API_VULKAN
#include <glm/ext/matrix_clip_space.hpp>
#include <glm/ext/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <openxr/openxr_platform.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult r, const char* what)
{
    if (r != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("XrBackend: ") + what + " failed: VkResult=" + std::to_string(r));
    }
}

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
    // Create the OpenXR instance immediately — VkContext needs the raw
    // handles in its Config to take the XR-bound init path. Session,
    // swapchains, and intermediate are deferred to init().
    xr_instance_ =
        std::make_unique<OpenXrInstance>(config_.app_name, config_.extra_xr_extensions, config_.system_wait_seconds);
}

XrBackend::~XrBackend()
{
    destroy();
}

XrInstance XrBackend::xr_instance_handle() const noexcept
{
    return xr_instance_ ? xr_instance_->instance() : XR_NULL_HANDLE;
}

XrSystemId XrBackend::xr_system_id() const noexcept
{
    return xr_instance_ ? xr_instance_->system_id() : XR_NULL_SYSTEM_ID;
}

void XrBackend::init(const VkContext& ctx, Resolution /*preferred_size*/)
{
    if (!xr_instance_)
    {
        throw std::logic_error("XrBackend::init: OpenXrInstance was destroyed");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("XrBackend::init: VkContext is not initialized");
    }
    ctx_ = &ctx;
    try
    {
        session_ = std::make_unique<OpenXrSession>(*xr_instance_, ctx, config_.session_config);
        swapchain_format_ = pick_swapchain_format();
        create_swapchains();
        // Depth submission is opt-in: only when the runtime advertised
        // XR_KHR_composition_layer_depth AND offers a usable depth
        // format. CloudXR uses depth for server-side reprojection;
        // runtimes without the extension just receive the projection
        // layer with no depth_info.
        depth_layer_enabled_ = xr_instance_->has_depth_composition_layer();
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
    // Order matters: tear down rendering resources first, then session,
    // then instance. The XR runtime owns the swapchain images so we
    // only need to xrDestroySwapchain (not vkDestroyImage) for those.
    render_target_.reset();
    destroy_swapchains();
    session_.reset();
    xr_instance_.reset();
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
    // Idempotent and exception-proof: clear frame_began_ BEFORE the
    // xrEndFrame call so a throw in the runtime can't recursively
    // re-enter via a destructor (or another abort path).
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
        // Best-effort. If the runtime is in a bad state we can't fix it
        // from here; the caller is typically already unwinding.
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
    // Enumerate runtime-supported formats and prefer sRGB-class color
    // formats matching the intermediate RT (which renders in linear
    // and presents through an SRGB color attachment).
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
    // Fall back: take whatever the runtime offers first. Rendering may
    // look wrong (no sRGB encode) but the protocol stays valid.
    return formats.front();
}

int64_t XrBackend::pick_depth_swapchain_format() const
{
    // Must match RenderTarget::depth_format() exactly — vkCmdCopyImage
    // requires identical formats for depth aspects (no blit fallback
    // for D/S formats). RenderTarget defaults to D32_SFLOAT; if the
    // runtime doesn't offer it we return 0 and depth submission is
    // disabled (projection layer goes out without depth_info).
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
    // Wide side-by-side intermediate: each view renders into its own
    // half (or N-th if more views exist). record_post_render_pass
    // splits the result and blits per-view region into per-view
    // swapchain images. This lets QuadLayer iterate views with
    // per-eye MVPs and produce real stereo content (with parallax).
    // For QuadLayer in fullscreen mode the per-view loop also runs
    // but each iteration just blits the texture into its half — the
    // result still matches the previous mono-into-stereo behavior.
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
// Convert XrPosef to a glm::mat4 representing the eye-to-world
// transform (i.e., the inverse is the view matrix used for rendering).
glm::mat4 pose_to_world_matrix(const XrPosef& pose)
{
    const glm::quat q(pose.orientation.w, pose.orientation.x, pose.orientation.y, pose.orientation.z);
    const glm::vec3 p(pose.position.x, pose.position.y, pose.position.z);
    return glm::translate(glm::mat4(1.0f), p) * glm::mat4_cast(q);
}

// Build the per-eye projection matrix from XR's signed-angle FOV.
// Conventions follow xr_plane_renderer (holohub):
//   - frustumRH_ZO = right-handed view, [0, 1] depth (Vulkan)
//   - bottom = nearZ * tan(angleUp), top = nearZ * tan(angleDown):
//     swapped because XR is Y-up and Vulkan clip is Y-down — the
//     swap effectively flips Y in the projection so XR-world +Y ends
//     up at Vulkan-clip -Y (top of screen).
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

    if (!last_frame_state_.shouldRender)
    {
        // Runtime is asking us to skip rendering this frame (e.g. headset
        // blacked out / app not focused). Submit an empty xrEndFrame to
        // balance xrBeginFrame. Order is critical: dismiss / clear state
        // ONLY after end_frame returns success. If end_frame throws, the
        // in_flight_guard still runs and abort_in_flight_frame retries
        // (with try/catch), so state is consistent on every path.
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
        frame_began_ = false;
        in_flight_guard.dismissed = true;
        return std::nullopt;
    }

    if (!session_->locate_views(last_frame_state_.predictedDisplayTime, &last_view_state_, &last_views_))
    {
        // Runtime can't locate views (tracking lost). Submit an empty
        // frame to keep the protocol balanced. Same ordering as above:
        // end_frame first, then dismiss.
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
        frame_began_ = false;
        in_flight_guard.dismissed = true;
        return std::nullopt;
    }

    // Locate the VIEW reference space — head pose at predicted_display_time.
    // Optional from a rendering standpoint (per-eye matrices already in
    // last_views_), but exposed via Frame::head_pose for layers / apps
    // doing head-locked placement. Tracking-loss returns false; the
    // method itself doesn't throw on XR_FAILED.
    XrSpaceLocation head_loc{ XR_TYPE_SPACE_LOCATION };
    const bool head_ok = session_->locate_view_space(last_frame_state_.predictedDisplayTime, &head_loc);

    // Acquire+wait one image from each per-view swapchain (color +
    // optional depth). `acquired` is flipped immediately after the
    // acquire call returns success — the spec requires every acquire
    // to be paired with a release regardless of whether the wait ran.
    // Setting acquired=true between acquire and wait means a wait
    // that throws still leaves the runtime accounting consistent for
    // the in_flight_guard's release pass.
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

    // Per-eye views populated from xrLocateViews. Each view gets its
    // own region of the wide intermediate (left half for view 0, right
    // half for view 1, ...) and its own view + projection matrices.
    // QuadLayer iterates views and either renders fullscreen per-eye
    // (legacy mode) or uses the MVP for true 3D placement.
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
        f.head_pose_valid = true;
    }
    f.wait_before_render = VK_NULL_HANDLE;
    f.signal_after_render = VK_NULL_HANDLE;
    f.backend_token = static_cast<uint64_t>(last_frame_state_.predictedDisplayTime);
    // Frame is fully built and the swapchains are acquired — hand the
    // protocol-balance baton off to the compositor's FrameGuard.
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
// Image barrier helper that takes the aspect mask explicitly — the
// shared transition_image at file scope hardcodes COLOR_BIT, which
// is wrong for depth attachments.
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

        // OpenXR expects the swapchain image in COLOR_ATTACHMENT_OPTIMAL
        // when xrEndFrame samples it for compositing.
        transition_image(cmd, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                         VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_COLOR_ATTACHMENT_READ_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT);
    }

    // Per-eye depth copy for XR_KHR_composition_layer_depth. Same
    // per-eye region split as color, but vkCmdCopyImage (not blit —
    // depth/stencil isn't blittable) since formats and dimensions
    // match (RT uses D32_SFLOAT, depth swapchain enforced D32_SFLOAT
    // in pick_depth_swapchain_format, and the per-eye region matches
    // recommendedImageRect). CloudXR consumes this for server-side
    // reprojection / late-stage warp.
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

            // Spec for XR_KHR_composition_layer_depth doesn't mandate
            // a specific layout at xrEndFrame, but DEPTH_STENCIL_READ_ONLY
            // is the conventional "runtime samples this" layout and
            // matches what Monado / CloudXR expect.
            transition_image_aspect(cmd, dst, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                                    VK_IMAGE_LAYOUT_DEPTH_STENCIL_READ_ONLY_OPTIMAL, VK_ACCESS_TRANSFER_WRITE_BIT,
                                    VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                                    VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
        }
    }
    (void)check_vk; // suppress unused-warning if no other VK errors get checked here
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

    // Release the swapchain images we acquired in begin_frame
    // (color + optional depth, in the same order they were acquired).
    // Clear `acquired` ONLY after release returns success — if release
    // throws, abort_frame's release pass should still see the image
    // as acquired and retry.
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

    // Per-eye depth_info (chained via .next on each ProjectionView).
    // Stored alongside proj_views so pointers stay valid through
    // xrEndFrame. min/maxDepth are the swapchain value range (Vulkan
    // [0,1]); near/farZ must match the projection matrix kNearZ/kFarZ
    // since the runtime uses them to reconstruct world-space depth.
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

    // Build per-eye projection views. Each references its own
    // swapchain (rendering blitted into all of them) at the full
    // recommended rect.
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
    // Non-opaque env blend modes (passthrough / additive) need the
    // runtime to honor our alpha channel; otherwise the projection
    // layer is treated as fully opaque and passthrough never shows.
    // Premultiplied bit not set — our shaders write straight alpha.
    const bool is_passthrough = session_->environment_blend_mode() != XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    projection_layer.layerFlags = is_passthrough ? XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT : 0;
    projection_layer.space = session_->reference_space();
    projection_layer.viewCount = static_cast<uint32_t>(proj_views.size());
    projection_layer.views = proj_views.data();

    const std::vector<const XrCompositionLayerBaseHeader*> layers = {
        reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection_layer),
    };
    // Clear protocol-balance state BEFORE the xrEndFrame call. This is the
    // single attempt that closes the begin/end pair; if it throws the
    // compositor's outer FrameGuard runs abort_frame, which would
    // otherwise see frame_began_=true and try a SECOND xrEndFrame on a
    // session that just rejected the first one (likely fatal session
    // loss — second call doubles the noise without helping). With the
    // flag cleared first, abort_frame's early-return on !frame_began_
    // makes the unwind a no-op and the original throw propagates cleanly.
    frame_began_ = false;
    frame_renderable_ = false;
    session_->end_frame(last_frame_state_.predictedDisplayTime, layers);
}

void XrBackend::abort_frame(const Frame& /*frame*/)
{
    // Compositor's submit threw before / during recording. The frame
    // was begun (xrBeginFrame happened in begin_frame) so we MUST
    // submit some xrEndFrame to balance the protocol — otherwise the
    // runtime gets stuck. Per-swapchain `acquired` flags drive the
    // release so partial-acquire state (e.g. color acquired, depth
    // never made it) gets cleaned up correctly. Idempotent: a frame
    // already aborted by the in-flight guard is a no-op.
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

XrBackend::OxrHandles XrBackend::oxr_handles() const noexcept
{
    OxrHandles h{};
    if (xr_instance_)
    {
        h.instance = xr_instance_->instance();
        // The loader-level entry is populated from libopenxr_loader's
        // exported xrGetInstanceProcAddr; static dispatch resolves it
        // at link time.
        h.xrGetInstanceProcAddr = ::xrGetInstanceProcAddr;
    }
    if (session_)
    {
        h.session = session_->session();
        h.reference_space = session_->reference_space();
        h.view_space = session_->view_space();
    }
    return h;
}

} // namespace viz
