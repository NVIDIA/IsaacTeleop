// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/shaders/textured_quad.frag.spv.h>
#include <viz/shaders/textured_quad.vert.spv.h>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("QuadLayer: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("QuadLayer: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

VkShaderModule create_shader_module(VkDevice device, const unsigned char* spv, size_t size)
{
    VkShaderModuleCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    info.codeSize = size;
    info.pCode = reinterpret_cast<const uint32_t*>(spv);
    VkShaderModule mod = VK_NULL_HANDLE;
    check_vk(vkCreateShaderModule(device, &info, nullptr, &mod), "vkCreateShaderModule");
    return mod;
}

// Once destroy() has run, slots_[0] is the canonical "alive" signal
// (it's the first thing init() builds and the last thing destroy()
// resets). Throwing logic_error converts use-after-destroy from a
// silent null-deref into a clean failure callers can catch in tests.
void require_alive(const std::unique_ptr<DeviceImage>& slot0, const char* what)
{
    if (!slot0)
    {
        throw std::logic_error(std::string("QuadLayer::") + what + " called after destroy()");
    }
}

// Mirrors textured_quad.vert's push_constant block.
//   mode = 0 → NDC-cover triangle, mvp ignored.
//   mode = 1 → 3D placed quad, mvp transforms local [-0.5, 0.5] to clip.
struct QuadShaderData
{
    float mvp[16];
    int32_t mode;
};
static_assert(sizeof(QuadShaderData) == sizeof(float) * 16 + sizeof(int32_t),
              "QuadShaderData layout must match textured_quad.vert");

// M = T(pose.position) · R(pose.orientation) · S(size.x, -size.y, 1).
// Negative Y on the scale matches Vulkan clip-space Y-down.
glm::mat4 placement_mvp(const QuadLayer::Config::Placement& p, const ViewInfo& view)
{
    glm::mat4 model = glm::translate(glm::mat4(1.0f), p.pose.position);
    model *= glm::mat4_cast(p.pose.orientation);
    model = glm::scale(model, glm::vec3(p.size_meters.x, -p.size_meters.y, 1.0f));
    return view.projection_matrix * view.view_matrix * model;
}

} // namespace

QuadLayer::QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config)
    : LayerBase(config.name), ctx_(&ctx), render_pass_(render_pass), config_(std::move(config))
{
    // textured_quad's frag samples a color image; depth views aren't
    // color-samplable.
    if (config_.format != PixelFormat::kRGBA8)
    {
        throw std::invalid_argument("QuadLayer: only PixelFormat::kRGBA8 is supported");
    }
    if (config_.resolution.width == 0 || config_.resolution.height == 0)
    {
        throw std::invalid_argument("QuadLayer: resolution must be non-zero");
    }
    if (render_pass == VK_NULL_HANDLE)
    {
        throw std::invalid_argument("QuadLayer: render_pass must be non-null");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("QuadLayer: VkContext is not initialized");
    }
    if (config_.placement.has_value())
    {
        const auto& ext = config_.placement->size_meters;
        if (ext.x <= 0.0f || ext.y <= 0.0f)
        {
            throw std::invalid_argument("QuadLayer: Placement::size_meters must be > 0 in both components");
        }
    }
    if (!std::isfinite(config_.stereo_baseline_mm))
    {
        throw std::invalid_argument("QuadLayer: stereo_baseline_mm must be finite");
    }

    // Resolve mip count: capped chain when enabled, single level
    // otherwise. The cap (kMaxMipLevels) keeps the per-frame blit
    // cost and the extra image storage in check; full log2 chain
    // adds levels that the sampler rarely picks anyway.
    if (config_.generate_mipmaps)
    {
        const uint32_t max_dim = std::max(config_.resolution.width, config_.resolution.height);
        uint32_t full_chain = 1;
        for (uint32_t d = max_dim; d > 1; d >>= 1)
        {
            ++full_chain;
        }
        mip_levels_ = std::min(full_chain, kMaxMipLevels);
    }
    else
    {
        mip_levels_ = 1;
    }

    placement_ = config_.placement;
    init();
}

QuadLayer::~QuadLayer()
{
    destroy();
}

void QuadLayer::init()
{
    try
    {
        // Atomic<uint8_t>'s default state is unspecified per the
        // standard; explicitly seed every entry to kSlotNone so submit
        // / record / get_wait_semaphores see a defined initial state.
        for (auto& e : in_use_)
        {
            e.store(kSlotNone, std::memory_order_relaxed);
        }
        last_in_use_slot_.store(kSlotNone, std::memory_order_relaxed);
        for (auto& slot : slots_)
        {
            slot = DeviceImage::create(*ctx_, config_.resolution, config_.format, mip_levels_);
        }
        if (config_.stereo)
        {
            for (auto& slot : slots_right_)
            {
                slot = DeviceImage::create(*ctx_, config_.resolution, config_.format, mip_levels_);
            }
        }
        create_sampler();
        create_descriptor_set_layout();
        create_pipeline_layout();
        create_pipeline();
        create_descriptor_pool();
        allocate_descriptor_sets();
        update_descriptor_sets();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void QuadLayer::destroy()
{
    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device == VK_NULL_HANDLE)
    {
        for (auto& slot : slots_)
        {
            slot.reset();
        }
        for (auto& slot : slots_right_)
        {
            slot.reset();
        }
        return;
    }
    if (descriptor_pool_ != VK_NULL_HANDLE)
    {
        // descriptor_sets_ + descriptor_sets_right_ are freed implicitly
        // with the pool.
        vkDestroyDescriptorPool(device, descriptor_pool_, nullptr);
        descriptor_pool_ = VK_NULL_HANDLE;
        descriptor_sets_.fill(VK_NULL_HANDLE);
        descriptor_sets_right_.fill(VK_NULL_HANDLE);
    }
    if (pipeline_ != VK_NULL_HANDLE)
    {
        vkDestroyPipeline(device, pipeline_, nullptr);
        pipeline_ = VK_NULL_HANDLE;
    }
    if (pipeline_layout_ != VK_NULL_HANDLE)
    {
        vkDestroyPipelineLayout(device, pipeline_layout_, nullptr);
        pipeline_layout_ = VK_NULL_HANDLE;
    }
    if (descriptor_set_layout_ != VK_NULL_HANDLE)
    {
        vkDestroyDescriptorSetLayout(device, descriptor_set_layout_, nullptr);
        descriptor_set_layout_ = VK_NULL_HANDLE;
    }
    if (sampler_ != VK_NULL_HANDLE)
    {
        vkDestroySampler(device, sampler_, nullptr);
        sampler_ = VK_NULL_HANDLE;
    }
    for (auto& slot : slots_)
    {
        slot.reset();
    }
    for (auto& slot : slots_right_)
    {
        slot.reset();
    }
    latest_.store(kSlotNone, std::memory_order_release);
    for (auto& e : in_use_)
    {
        e.store(kSlotNone, std::memory_order_release);
    }
    last_in_use_slot_.store(kSlotNone, std::memory_order_release);
}

Resolution QuadLayer::resolution() const noexcept
{
    return config_.resolution;
}

PixelFormat QuadLayer::format() const noexcept
{
    return config_.format;
}

std::optional<float> QuadLayer::aspect_ratio() const noexcept
{
    if (config_.resolution.height == 0)
    {
        return std::nullopt;
    }
    return static_cast<float>(config_.resolution.width) / static_cast<float>(config_.resolution.height);
}

const DeviceImage* QuadLayer::device_image(uint32_t slot) const noexcept
{
    if (slot >= kSlotCount)
    {
        return nullptr;
    }
    return slots_[slot].get();
}

const DeviceImage* QuadLayer::device_image_right(uint32_t slot) const noexcept
{
    if (slot >= kSlotCount)
    {
        return nullptr;
    }
    return slots_right_[slot].get();
}

uint8_t QuadLayer::pick_free_slot(uint8_t latest,
                                  const std::array<std::atomic<uint8_t>, kMaxFramesInFlight>& in_use) const noexcept
{
    // Forbidden = {latest} ∪ in_use_. kSlotCount = kMaxFramesInFlight + 2
    // guarantees one free slot under the invariant; we still return
    // kSlotNone defensively if the invariant ever breaks, so submit()
    // drops the publish rather than overwriting a slot the GPU is sampling.
    static_assert(kSlotCount > kMaxFramesInFlight + 1,
                  "kSlotCount must exceed kMaxFramesInFlight + 1 so at least one slot is free");
    for (uint8_t i = 0; i < kSlotCount; ++i)
    {
        if (i == latest)
            continue;
        bool conflicts = false;
        for (uint32_t k = 0; k < kMaxFramesInFlight; ++k)
        {
            if (i == in_use[k].load(std::memory_order_acquire))
            {
                conflicts = true;
                break;
            }
        }
        if (!conflicts)
        {
            return i;
        }
    }
    return kSlotNone;
}

namespace
{
// Shared per-buffer validation for the submit overloads. ``label`` is
// the caller's tag (e.g. "src", "left", "right") so the error message
// names which buffer failed in the stereo case.
void validate_submit_buffer(const VizBuffer& buf, const QuadLayer::Config& cfg, const char* label)
{
    if (buf.space != MemorySpace::kDevice)
    {
        throw std::invalid_argument(std::string("QuadLayer::submit: ") + label + " must be MemorySpace::kDevice");
    }
    if (buf.width != cfg.resolution.width || buf.height != cfg.resolution.height)
    {
        throw std::invalid_argument(std::string("QuadLayer::submit: ") + label +
                                    " dimensions do not match layer resolution");
    }
    if (buf.format != cfg.format)
    {
        throw std::invalid_argument(std::string("QuadLayer::submit: ") + label + " format does not match layer format");
    }
    if (buf.data == nullptr)
    {
        throw std::invalid_argument(std::string("QuadLayer::submit: ") + label + ".data is null");
    }
}

// Queue an async D2D copy of ``buf`` → ``image.cuda_array()`` on
// ``stream``. Shared between the mono and stereo submit paths.
void enqueue_copy(const VizBuffer& buf, DeviceImage& image, cudaStream_t stream)
{
    const size_t row_bytes = static_cast<size_t>(buf.width) * bytes_per_pixel(buf.format);
    const size_t src_pitch = (buf.pitch == 0) ? row_bytes : buf.pitch;
    const cudaError_t err = cudaMemcpy2DToArrayAsync(
        image.cuda_array(), 0, 0, buf.data, src_pitch, row_bytes, buf.height, cudaMemcpyDeviceToDevice, stream);
    if (err != cudaSuccess)
    {
        throw std::runtime_error(std::string("QuadLayer::submit: cudaMemcpy2DToArrayAsync failed: ") +
                                 cudaGetErrorString(err));
    }
}
} // namespace

void QuadLayer::submit(const VizBuffer& src, cudaStream_t stream)
{
    require_alive(slots_[0], "submit");
    if (config_.stereo)
    {
        throw std::logic_error("QuadLayer::submit: this layer is stereo — use the two-arg submit(left, right) overload");
    }
    validate_submit_buffer(src, config_, "src");

    const uint8_t latest = latest_.load(std::memory_order_acquire);
    const uint8_t slot = pick_free_slot(latest, in_use_);
    if (slot == kSlotNone)
    {
        // Mailbox drop: producer outran the renderer beyond the sizing
        // invariant. Keep latest_ where it is; consumer keeps using it.
        return;
    }
    DeviceImage& image = *slots_[slot];

    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");
    enqueue_copy(src, image, stream);
    image.cuda_signal_write_done(stream);

    // Wait for the D2D copy to complete before returning. Sources publish
    // buffers by reference and treat ``latest()`` returning them as proof
    // of consumption; without a sync here a fast producer could wrap the
    // mailbox and overwrite src.data while our async memcpy is still
    // reading from it. Cost is ~0.5 ms per 1080p submit on the caller's
    // thread; the render path is unaffected.
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(submit)");

    // memory_order_release pairs with the renderer's acquire load.
    latest_.store(slot, std::memory_order_release);
}

void QuadLayer::submit(const VizBuffer& left, const VizBuffer& right, cudaStream_t stream)
{
    require_alive(slots_[0], "submit");
    if (!config_.stereo)
    {
        throw std::logic_error("QuadLayer::submit: this layer is mono — call submit(src) with a single buffer");
    }
    validate_submit_buffer(left, config_, "left");
    validate_submit_buffer(right, config_, "right");

    const uint8_t latest = latest_.load(std::memory_order_acquire);
    const uint8_t slot = pick_free_slot(latest, in_use_);
    if (slot == kSlotNone)
    {
        return;
    }
    DeviceImage& image_l = *slots_[slot];
    DeviceImage& image_r = *slots_right_[slot];

    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");
    // Both copies on the same stream + a single signal on the left's
    // semaphore. Stream ordering guarantees the right copy completes
    // before the signal fires, so the renderer waiting on the left's
    // semaphore implies the right is ready too. No second semaphore
    // needed — by construction the renderer cannot see a half-pair.
    enqueue_copy(left, image_l, stream);
    enqueue_copy(right, image_r, stream);
    image_l.cuda_signal_write_done(stream);

    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(submit-stereo)");

    latest_.store(slot, std::memory_order_release);
}

void QuadLayer::record_mip_generation(VkCommandBuffer cmd, DeviceImage& image)
{
    // Mip-chain regeneration via vkCmdBlitImage. The image lives in
    // SHADER_READ_ONLY between frames (set in DeviceImage::init); we
    // cycle through TRANSFER layouts and return to SHADER_READ_ONLY so
    // the post-pass sample sees the same invariant. CUDA wrote level 0
    // out-of-band; the queue submit's TRANSFER-stage wait on
    // cuda_done_writing gates this against the producer (see
    // get_wait_semaphores).
    const VkImage vk_image = image.vk_image();
    const uint32_t levels = image.mip_levels();
    const int32_t base_w = static_cast<int32_t>(image.resolution().width);
    const int32_t base_h = static_cast<int32_t>(image.resolution().height);

    auto barrier_one_level = [&](uint32_t level, VkImageLayout old_layout, VkImageLayout new_layout,
                                 VkAccessFlags src_access, VkAccessFlags dst_access, VkPipelineStageFlags src_stage,
                                 VkPipelineStageFlags dst_stage)
    {
        VkImageMemoryBarrier b{};
        b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        b.oldLayout = old_layout;
        b.newLayout = new_layout;
        b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.image = vk_image;
        b.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        b.subresourceRange.baseMipLevel = level;
        b.subresourceRange.levelCount = 1;
        b.subresourceRange.baseArrayLayer = 0;
        b.subresourceRange.layerCount = 1;
        b.srcAccessMask = src_access;
        b.dstAccessMask = dst_access;
        vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &b);
    };

    // Level 0: SHADER_READ -> TRANSFER_SRC (will be read by the first blit).
    barrier_one_level(0, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                      VK_ACCESS_SHADER_READ_BIT, VK_ACCESS_TRANSFER_READ_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                      VK_PIPELINE_STAGE_TRANSFER_BIT);
    // Levels 1..N-1: SHADER_READ -> TRANSFER_DST (will be overwritten).
    for (uint32_t i = 1; i < levels; ++i)
    {
        barrier_one_level(i, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                          VK_ACCESS_SHADER_READ_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
                          VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
    }

    int32_t src_w = base_w;
    int32_t src_h = base_h;
    for (uint32_t i = 1; i < levels; ++i)
    {
        const int32_t dst_w = std::max(1, src_w >> 1);
        const int32_t dst_h = std::max(1, src_h >> 1);

        VkImageBlit blit{};
        blit.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        blit.srcSubresource.mipLevel = i - 1;
        blit.srcSubresource.baseArrayLayer = 0;
        blit.srcSubresource.layerCount = 1;
        blit.srcOffsets[0] = { 0, 0, 0 };
        blit.srcOffsets[1] = { src_w, src_h, 1 };
        blit.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        blit.dstSubresource.mipLevel = i;
        blit.dstSubresource.baseArrayLayer = 0;
        blit.dstSubresource.layerCount = 1;
        blit.dstOffsets[0] = { 0, 0, 0 };
        blit.dstOffsets[1] = { dst_w, dst_h, 1 };

        vkCmdBlitImage(cmd, vk_image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, vk_image,
                       VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &blit, VK_FILTER_LINEAR);

        // Promote level i to TRANSFER_SRC so the next blit can read it.
        // Last level skips this — the final sweep below moves it
        // straight from TRANSFER_DST to SHADER_READ.
        if (i + 1 < levels)
        {
            barrier_one_level(i, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                              VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                              VK_PIPELINE_STAGE_TRANSFER_BIT);
        }

        src_w = dst_w;
        src_h = dst_h;
    }

    // Final sweep: levels 0..N-2 are in TRANSFER_SRC, level N-1 is in
    // TRANSFER_DST. One barrier each back to SHADER_READ.
    for (uint32_t i = 0; i + 1 < levels; ++i)
    {
        barrier_one_level(i, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                          VK_ACCESS_TRANSFER_READ_BIT, VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                          VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
    }
    barrier_one_level(levels - 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                      VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                      VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT);
}

void QuadLayer::record_pre_render_pass(VkCommandBuffer cmd, uint32_t in_flight_slot)
{
    require_alive(slots_[0], "record_pre_render_pass");

    // Backends are contracted to image_count <= kMaxFramesInFlight; if
    // that ever breaks, two in-flight frames would alias on the same
    // in_use_ entry and we'd lose the slot-tracking invariant.
    if (in_flight_slot >= kMaxFramesInFlight)
    {
        throw std::logic_error("QuadLayer::record_pre_render_pass: in_flight_slot " + std::to_string(in_flight_slot) +
                               " >= kMaxFramesInFlight (" + std::to_string(kMaxFramesInFlight) +
                               "); bump kMaxFramesInFlight to match the backend's image_count");
    }

    // Promote latest_ -> in_use_[in_flight_slot]. The compositor's
    // per-slot fence wait at the top of render() guarantees the GPU
    // has finished sampling the previous in_use_ value. record() reads
    // the same entry — pre-pass and pass MUST agree on in_flight_slot.
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    const uint32_t idx = in_flight_slot;
    if (latest != kSlotNone)
    {
        in_use_[idx].store(latest, std::memory_order_release);
    }
    const uint8_t cur = in_use_[idx].load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return;
    }
    // Record which slot this frame is sampling so get_wait_semaphores
    // (called by compositor between record and submit) reads the
    // matching cuda_done_writing semaphore.
    last_in_use_slot_.store(cur, std::memory_order_release);

    // Mip generation (if configured). Reads level 0 written by CUDA,
    // writes levels 1..N-1, ends with the whole image back in
    // SHADER_READ_ONLY for the sampler in record(). For stereo we
    // regenerate both eyes' chains; the right image's level 0 was
    // written by the same producer stream that signaled the left's
    // semaphore, so the queue's TRANSFER-stage wait already covers it.
    if (mip_levels_ > 1)
    {
        record_mip_generation(cmd, *slots_[cur]);
        if (config_.stereo)
        {
            record_mip_generation(cmd, *slots_right_[cur]);
        }
    }
}

void QuadLayer::record(VkCommandBuffer cmd,
                       const std::vector<ViewInfo>& views,
                       const RenderTarget& /*target*/,
                       uint32_t in_flight_slot)
{
    require_alive(slots_[0], "record");

    // Slot promotion ran in record_pre_render_pass with the same
    // in_flight_slot. Read the result; skip the draw if there's been
    // no publish yet (RT keeps its clear value).
    const uint32_t idx = in_flight_slot;
    const uint8_t cur = in_use_[idx].load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return;
    }

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_);

    // Snapshot under lock so set_placement() can run concurrently.
    std::optional<Config::Placement> placement;
    {
        std::lock_guard<std::mutex> lk(placement_mutex_);
        placement = placement_;
    }
    const bool xr_mode = session() != nullptr && session()->is_xr_mode();
    if (xr_mode && !placement.has_value())
    {
        throw std::logic_error(
            "QuadLayer: XR mode requires Config::placement to be set "
            "(fullscreen quads in stereo XR are not supported)");
    }

    // xr: 4-vertex triangle strip; else: 3-vertex NDC-cover triangle.
    const uint32_t vertex_count = xr_mode ? 4u : 3u;

    // Stereo baseline offset along the placement's local +x axis. ±half
    // the configured baseline, signed per eye: left eye gets the
    // negative offset, right eye the positive. Direction in world space
    // is the placement orientation rotating local +x. We evaluate it
    // once outside the per-view loop since orientation is per-frame
    // constant. Skipped when the layer is mono (baseline doesn't apply)
    // OR outside kXr (both eyes converge to a single view, no signed
    // disambiguation possible). Zero baseline elides to the mono MVP.
    const bool apply_baseline = xr_mode && config_.stereo && config_.stereo_baseline_mm != 0.0f;
    glm::vec3 baseline_axis_ws{ 0.0f };
    if (apply_baseline)
    {
        baseline_axis_ws = glm::mat3_cast(placement->pose.orientation) * glm::vec3(1.0f, 0.0f, 0.0f);
    }

    // Compositor pre-binds the layer's scissor; we set per-view viewport.
    for (size_t view_idx = 0; view_idx < views.size(); ++view_idx)
    {
        const auto& view = views[view_idx];
        bind_view_viewport(cmd, view);

        // Stereo: view 0 → left descriptor, view 1 → right descriptor.
        // Mono OR single-view backends (window/offscreen): always left.
        const bool sample_right = config_.stereo && view_idx == 1;
        VkDescriptorSet ds = sample_right ? descriptor_sets_right_[cur] : descriptor_sets_[cur];
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_layout_, 0, 1, &ds, 0, nullptr);

        QuadShaderData data{};
        if (xr_mode)
        {
            Config::Placement eye_placement = *placement;
            if (apply_baseline)
            {
                const float sign = (view_idx == 0) ? -1.0f : +1.0f;
                // 0.5 to halve the disparity per eye, 0.001 to convert mm → m
                // (placement.pose.position is in world meters).
                eye_placement.pose.position += sign * (config_.stereo_baseline_mm * 0.0005f) * baseline_axis_ws;
            }
            const glm::mat4 mvp = placement_mvp(eye_placement, view);
            std::memcpy(data.mvp, &mvp[0][0], sizeof(data.mvp));
            data.mode = 1;
        }
        // mode=0 (default): MVP unused.
        vkCmdPushConstants(cmd, pipeline_layout_, VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(data), &data);
        vkCmdDraw(cmd, vertex_count, 1, 0, 0);
    }
}

void QuadLayer::set_placement(std::optional<Config::Placement> placement) noexcept
{
    std::lock_guard<std::mutex> lk(placement_mutex_);
    placement_ = std::move(placement);
}

std::optional<QuadLayer::Config::Placement> QuadLayer::placement() const noexcept
{
    std::lock_guard<std::mutex> lk(placement_mutex_);
    return placement_;
}

std::vector<LayerBase::WaitSemaphore> QuadLayer::get_wait_semaphores() const
{
    // Compositor calls record_pre_render_pass first (which sets
    // last_in_use_slot_). We return THAT slot's cuda_done_writing
    // semaphore so the submit waits for the producer's memcpy.
    // Wait stage:
    //   * No mips: first GPU read is the fragment sampler.
    //   * Mips on: the mip-gen blit chain in pre-pass reads level 0
    //     first (TRANSFER stage); fragment sampling comes later but
    //     is already ordered via the chain's barriers, so the submit
    //     wait can gate at TRANSFER.
    const uint8_t cur = last_in_use_slot_.load(std::memory_order_acquire);
    if (cur == kSlotNone || !slots_[cur])
    {
        return {};
    }
    const DeviceImage& image = *slots_[cur];
    const uint64_t value = image.cuda_done_writing_value();
    if (value == 0)
    {
        return {};
    }
    const VkPipelineStageFlags wait_stage =
        (mip_levels_ > 1) ? VK_PIPELINE_STAGE_TRANSFER_BIT : VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
    return {
        WaitSemaphore{
            image.cuda_done_writing(),
            value,
            wait_stage,
        },
    };
}

void QuadLayer::create_sampler()
{
    const bool mips_on = mip_levels_ > 1;
    VkSamplerCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    info.magFilter = VK_FILTER_LINEAR;
    info.minFilter = VK_FILTER_LINEAR;
    // Trilinear when mips are on (LINEAR mode interpolates between two
    // chain levels). NEAREST is harmless single-level since the lod
    // range collapses to 0.
    info.mipmapMode = mips_on ? VK_SAMPLER_MIPMAP_MODE_LINEAR : VK_SAMPLER_MIPMAP_MODE_NEAREST;
    info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.anisotropyEnable = VK_FALSE;
    info.maxAnisotropy = 1.0f;
    info.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    info.unnormalizedCoordinates = VK_FALSE;
    info.compareEnable = VK_FALSE;
    info.compareOp = VK_COMPARE_OP_ALWAYS;
    info.mipLodBias = 0.0f;
    info.minLod = 0.0f;
    info.maxLod = mips_on ? static_cast<float>(mip_levels_ - 1) : 0.0f;
    check_vk(vkCreateSampler(ctx_->device(), &info, nullptr, &sampler_), "vkCreateSampler");
}

void QuadLayer::create_descriptor_set_layout()
{
    VkDescriptorSetLayoutBinding binding{};
    binding.binding = 0;
    binding.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    binding.descriptorCount = 1;
    binding.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    binding.pImmutableSamplers = nullptr;

    VkDescriptorSetLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    info.bindingCount = 1;
    info.pBindings = &binding;
    check_vk(vkCreateDescriptorSetLayout(ctx_->device(), &info, nullptr, &descriptor_set_layout_),
             "vkCreateDescriptorSetLayout");
}

void QuadLayer::create_pipeline_layout()
{
    // Push constants: mat4 mvp + int32 mode = 68 bytes, well under
    // the spec's 128-byte minimum guarantee.
    VkPushConstantRange pc_range{};
    pc_range.stageFlags = VK_SHADER_STAGE_VERTEX_BIT;
    pc_range.offset = 0;
    pc_range.size = sizeof(float) * 16 + sizeof(int32_t);

    VkPipelineLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    info.setLayoutCount = 1;
    info.pSetLayouts = &descriptor_set_layout_;
    info.pushConstantRangeCount = 1;
    info.pPushConstantRanges = &pc_range;
    check_vk(vkCreatePipelineLayout(ctx_->device(), &info, nullptr, &pipeline_layout_), "vkCreatePipelineLayout");
}

void QuadLayer::create_pipeline()
{
    const VkDevice device = ctx_->device();

    VkShaderModule vert =
        create_shader_module(device, viz::shaders::kTexturedQuadVertSpv, viz::shaders::kTexturedQuadVertSpvSize);
    VkShaderModule frag =
        create_shader_module(device, viz::shaders::kTexturedQuadFragSpv, viz::shaders::kTexturedQuadFragSpvSize);

    // RAII: shader modules are only needed during pipeline creation.
    struct ShaderGuard
    {
        VkDevice device;
        VkShaderModule vert;
        VkShaderModule frag;
        ~ShaderGuard()
        {
            if (vert != VK_NULL_HANDLE)
            {
                vkDestroyShaderModule(device, vert, nullptr);
            }
            if (frag != VK_NULL_HANDLE)
            {
                vkDestroyShaderModule(device, frag, nullptr);
            }
        }
    } guard{ device, vert, frag };

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vert;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = frag;
    stages[1].pName = "main";

    VkPipelineVertexInputStateCreateInfo vertex_input{};
    vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo input_assembly{};
    input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    // TRIANGLE_STRIP works for both render modes (see textured_quad.vert):
    //   3 verts → 1 triangle (fullscreen pass; same as TRIANGLE_LIST)
    //   4 verts → 2 triangles (3D placed quad)
    input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;

    // Viewport / scissor are dynamic so one pipeline works across
    // resolutions.
    VkPipelineViewportStateCreateInfo viewport_state{};
    viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewport_state.viewportCount = 1;
    viewport_state.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterizer.lineWidth = 1.0f;

    VkPipelineMultisampleStateCreateInfo multisample{};
    multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    // Depth disabled — fullscreen blits don't need it.
    // Depth on so XR backends can submit XrCompositionLayerDepthInfoKHR
    // alongside the projection layer (CloudXR uses depth for server-
    // side reprojection). LESS_OR_EQUAL keeps last-wins semantics for
    // overlapping layers when multiple QuadLayers stack at z = 0
    // (fullscreen mode); meaningful for true depth-sort once 3D-placed
    // QuadLayers are in active use.
    VkPipelineDepthStencilStateCreateInfo depth_stencil{};
    depth_stencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depth_stencil.depthTestEnable = VK_TRUE;
    depth_stencil.depthWriteEnable = VK_TRUE;
    depth_stencil.depthCompareOp = VK_COMPARE_OP_LESS_OR_EQUAL;

    VkPipelineColorBlendAttachmentState blend_attachment{};
    blend_attachment.blendEnable = VK_FALSE;
    blend_attachment.colorWriteMask =
        VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;

    VkPipelineColorBlendStateCreateInfo color_blend{};
    color_blend.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    color_blend.attachmentCount = 1;
    color_blend.pAttachments = &blend_attachment;

    const VkDynamicState dynamic_states[] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo dynamic{};
    dynamic.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamic.dynamicStateCount = sizeof(dynamic_states) / sizeof(dynamic_states[0]);
    dynamic.pDynamicStates = dynamic_states;

    VkGraphicsPipelineCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    info.stageCount = 2;
    info.pStages = stages;
    info.pVertexInputState = &vertex_input;
    info.pInputAssemblyState = &input_assembly;
    info.pViewportState = &viewport_state;
    info.pRasterizationState = &rasterizer;
    info.pMultisampleState = &multisample;
    info.pDepthStencilState = &depth_stencil;
    info.pColorBlendState = &color_blend;
    info.pDynamicState = &dynamic;
    info.layout = pipeline_layout_;
    info.renderPass = render_pass_;
    info.subpass = 0;

    check_vk(vkCreateGraphicsPipelines(device, ctx_->pipeline_cache(), 1, &info, nullptr, &pipeline_),
             "vkCreateGraphicsPipelines");
}

void QuadLayer::create_descriptor_pool()
{
    // Stereo needs twice the sets: one per slot per eye.
    const uint32_t set_count = config_.stereo ? (kSlotCount * 2u) : kSlotCount;

    VkDescriptorPoolSize pool_size{};
    pool_size.type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    pool_size.descriptorCount = set_count;

    VkDescriptorPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    info.maxSets = set_count;
    info.poolSizeCount = 1;
    info.pPoolSizes = &pool_size;
    check_vk(vkCreateDescriptorPool(ctx_->device(), &info, nullptr, &descriptor_pool_), "vkCreateDescriptorPool");
}

void QuadLayer::allocate_descriptor_sets()
{
    std::array<VkDescriptorSetLayout, kSlotCount> layouts{};
    layouts.fill(descriptor_set_layout_);

    VkDescriptorSetAllocateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    info.descriptorPool = descriptor_pool_;
    info.descriptorSetCount = kSlotCount;
    info.pSetLayouts = layouts.data();
    check_vk(vkAllocateDescriptorSets(ctx_->device(), &info, descriptor_sets_.data()), "vkAllocateDescriptorSets");
    if (config_.stereo)
    {
        check_vk(vkAllocateDescriptorSets(ctx_->device(), &info, descriptor_sets_right_.data()),
                 "vkAllocateDescriptorSets(right)");
    }
}

void QuadLayer::update_descriptor_sets()
{
    // One write per slot per eye, pointing at the eye-specific image
    // view. Stereo doubles the write count.
    const uint32_t per_eye = kSlotCount;
    const uint32_t total = config_.stereo ? (per_eye * 2u) : per_eye;

    std::array<VkDescriptorImageInfo, kSlotCount * 2> image_infos{};
    std::array<VkWriteDescriptorSet, kSlotCount * 2> writes{};

    for (uint32_t i = 0; i < per_eye; ++i)
    {
        image_infos[i].sampler = sampler_;
        image_infos[i].imageView = slots_[i]->vk_image_view();
        image_infos[i].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = descriptor_sets_[i];
        writes[i].dstBinding = 0;
        writes[i].dstArrayElement = 0;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[i].pImageInfo = &image_infos[i];
    }
    if (config_.stereo)
    {
        for (uint32_t i = 0; i < per_eye; ++i)
        {
            const uint32_t k = per_eye + i;
            image_infos[k].sampler = sampler_;
            image_infos[k].imageView = slots_right_[i]->vk_image_view();
            image_infos[k].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

            writes[k].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
            writes[k].dstSet = descriptor_sets_right_[i];
            writes[k].dstBinding = 0;
            writes[k].dstArrayElement = 0;
            writes[k].descriptorCount = 1;
            writes[k].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
            writes[k].pImageInfo = &image_infos[k];
        }
    }
    vkUpdateDescriptorSets(ctx_->device(), total, writes.data(), 0, nullptr);
}

} // namespace viz
