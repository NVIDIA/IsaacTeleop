// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/session/xr_backend.hpp>
#include <viz/xr/openxr_instance.hpp>

#define XR_USE_GRAPHICS_API_VULKAN
#include <openxr/openxr_platform.h>

#include <algorithm>
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
    // Phase 1: monoscopic render at view 0's recommended resolution;
    // both eyes blit from the same intermediate. Use the COLOR
    // attachment format of the RT's render pass — RT picks its own.
    const auto& v0 = session_->view_configuration_views()[0];
    RenderTarget::Config rt_cfg{};
    rt_cfg.resolution = Resolution{ v0.recommendedImageRectWidth, v0.recommendedImageRectHeight };
    render_target_ = RenderTarget::create(*ctx_, rt_cfg);
}

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

    if (!last_frame_state_.shouldRender)
    {
        // Runtime is asking us to skip rendering this frame (e.g. headset
        // blacked out / app not focused). Still must call xrEndFrame to
        // balance xrBeginFrame; do that path through abort_frame on the
        // FrameGuard. Returning nullopt also causes VizCompositor to skip
        // the submit — backend will get end_frame via the no-frame path
        // (caller doesn't pair end_frame on nullopt). We need to call
        // xrEndFrame ourselves before returning nullopt.
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
        frame_began_ = false;
        return std::nullopt;
    }

    if (!session_->locate_views(last_frame_state_.predictedDisplayTime, &last_view_state_, &last_views_))
    {
        // Runtime can't locate views (tracking lost). Submit an empty
        // frame to keep the protocol balanced.
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
        frame_began_ = false;
        return std::nullopt;
    }

    // Acquire+wait one image from each per-view swapchain.
    for (auto& sw : view_swapchains_)
    {
        XrSwapchainImageAcquireInfo acquire_info{ XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO };
        check_xr(xrAcquireSwapchainImage(sw.handle, &acquire_info, &sw.current_image_index), "xrAcquireSwapchainImage");
        XrSwapchainImageWaitInfo wait_info{ XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO };
        wait_info.timeout = XR_INFINITE_DURATION;
        check_xr(xrWaitSwapchainImage(sw.handle, &wait_info), "xrWaitSwapchainImage");
    }
    frame_renderable_ = true;

    // Single canonical view spanning the whole intermediate. The
    // intermediate is monoscopic in Phase 1; per-eye composition
    // happens at xrEndFrame via two ProjectionViews (built in
    // end_frame) that both reference our blits below.
    Frame f{};
    f.views.assign(1, ViewInfo{});
    f.views[0].viewport = Rect2D{ 0, 0, render_target_->resolution().width, render_target_->resolution().height };
    f.wait_before_render = VK_NULL_HANDLE;
    f.signal_after_render = VK_NULL_HANDLE;
    f.backend_token = static_cast<uint64_t>(last_frame_state_.predictedDisplayTime);
    // Surface the runtime's pacing target so app code (FrameInfo
    // consumers) can locate spaces / drive animations to display time.
    f.predicted_display_time = static_cast<int64_t>(last_frame_state_.predictedDisplayTime);
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

void XrBackend::record_post_render_pass(VkCommandBuffer cmd, const Frame& /*frame*/)
{
    if (!frame_renderable_ || !render_target_)
    {
        return;
    }
    const VkImage src = render_target_->color_image();
    const Resolution src_extent = render_target_->resolution();

    // Blit the same intermediate to every per-eye swapchain image.
    // RT's color attachment is in TRANSFER_SRC_OPTIMAL after the render
    // pass's final layout. Each XR swapchain image arrives in an
    // unspecified layout (per spec: contents undefined post-acquire),
    // so we transition UNDEFINED -> TRANSFER_DST -> COLOR_ATTACHMENT.
    for (const auto& sw : view_swapchains_)
    {
        const VkImage dst = sw.images[sw.current_image_index];
        transition_image(cmd, dst, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
                         VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);

        VkImageBlit region{};
        region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.srcSubresource.layerCount = 1;
        region.srcOffsets[1] = { static_cast<int32_t>(src_extent.width), static_cast<int32_t>(src_extent.height), 1 };
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

    // Release the swapchain images we acquired in begin_frame.
    for (auto& sw : view_swapchains_)
    {
        XrSwapchainImageReleaseInfo release_info{ XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
        check_xr(xrReleaseSwapchainImage(sw.handle, &release_info), "xrReleaseSwapchainImage");
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
    }

    XrCompositionLayerProjection projection_layer{ XR_TYPE_COMPOSITION_LAYER_PROJECTION };
    projection_layer.layerFlags = 0;
    projection_layer.space = session_->reference_space();
    projection_layer.viewCount = static_cast<uint32_t>(proj_views.size());
    projection_layer.views = proj_views.data();

    const std::vector<const XrCompositionLayerBaseHeader*> layers = {
        reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projection_layer),
    };
    session_->end_frame(last_frame_state_.predictedDisplayTime, layers);

    frame_began_ = false;
    frame_renderable_ = false;
}

void XrBackend::abort_frame(const Frame& /*frame*/)
{
    // Compositor's submit threw before / during recording. The frame
    // was begun (xrBeginFrame happened in begin_frame) so we MUST
    // submit some xrEndFrame to balance the protocol — otherwise the
    // runtime gets stuck. Release any swapchain images we acquired
    // and submit empty layers.
    if (!frame_began_)
    {
        return;
    }
    if (frame_renderable_)
    {
        for (auto& sw : view_swapchains_)
        {
            XrSwapchainImageReleaseInfo release_info{ XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
            (void)xrReleaseSwapchainImage(sw.handle, &release_info);
        }
    }
    try
    {
        session_->end_frame(last_frame_state_.predictedDisplayTime, {});
    }
    catch (...)
    {
        // Swallow — abort_frame mustn't throw (called from a frame
        // guard's destructor in the compositor).
    }
    frame_began_ = false;
    frame_renderable_ = false;
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
    }
    return h;
}

} // namespace viz
