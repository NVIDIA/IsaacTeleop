// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <stdexcept>
#include <string>
#include <utility>

namespace viz
{

namespace
{

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("ProjectionLayer: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

} // namespace

ProjectionLayer::ProjectionLayer(const VkContext& ctx, Config config)
    : LayerBase(config.name), ctx_(&ctx), config_(std::move(config))
{
    // Validate config first (cheap, no resources), then the context.
    // Config checks don't depend on ctx, and ordering them first lets them
    // be unit-tested without a GPU-initialized VkContext.
    if (config_.view_resolution.width == 0 || config_.view_resolution.height == 0)
    {
        throw std::invalid_argument("ProjectionLayer: view_resolution must be non-zero");
    }
    if (config_.color_format != PixelFormat::kRGBA8)
    {
        throw std::invalid_argument("ProjectionLayer: color_format must be kRGBA8");
    }
    if (config_.depth_format.has_value() && config_.depth_format.value() != PixelFormat::kD32F)
    {
        throw std::invalid_argument("ProjectionLayer: depth_format must be kD32F or nullopt");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("ProjectionLayer: VkContext not initialized");
    }
    view_count_ = config_.stereo ? 2u : 1u;
    has_depth_ = config_.depth_format.has_value();
    for (auto& slot : in_use_)
    {
        slot.store(kSlotNone, std::memory_order_relaxed);
    }
    init();
}

ProjectionLayer::~ProjectionLayer()
{
    destroy();
}

void ProjectionLayer::init()
{
    // The only resources this layer owns are the per-eye (color, depth)
    // mailbox DeviceImages. There is no render pipeline — the backend
    // copies these images straight to the swapchains.
    try
    {
        for (uint32_t s = 0; s < kSlotCount; ++s)
        {
            slots_color_[s].reserve(view_count_);
            for (uint32_t v = 0; v < view_count_; ++v)
            {
                slots_color_[s].push_back(DeviceImage::create(*ctx_, config_.view_resolution, config_.color_format, 1));
            }
            if (has_depth_)
            {
                slots_depth_[s].reserve(view_count_);
                for (uint32_t v = 0; v < view_count_; ++v)
                {
                    slots_depth_[s].push_back(
                        DeviceImage::create(*ctx_, config_.view_resolution, *config_.depth_format, 1));
                }
            }
        }
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void ProjectionLayer::destroy()
{
    // Drain pending GPU work before freeing the images the compositor's
    // command buffers reference.
    if (ctx_ != nullptr && ctx_->device() != VK_NULL_HANDLE)
    {
        (void)vkDeviceWaitIdle(ctx_->device());
    }
    for (uint32_t s = 0; s < kSlotCount; ++s)
    {
        slots_color_[s].clear();
        slots_depth_[s].clear();
    }
}

// ─── Submit ──────────────────────────────────────────────────────────

void ProjectionLayer::validate_submit_buffer(const VizBuffer& buf, PixelFormat expected_format, const char* label) const
{
    if (buf.data == nullptr)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": data is null");
    }
    if (buf.space != MemorySpace::kDevice)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": MemorySpace must be kDevice");
    }
    if (buf.format != expected_format)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": pixel format mismatch");
    }
    if (buf.width != config_.view_resolution.width || buf.height != config_.view_resolution.height)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": resolution mismatch");
    }
}

void ProjectionLayer::enqueue_copy(const VizBuffer& src, DeviceImage& dst, cudaStream_t stream) const
{
    const size_t row_bytes = static_cast<size_t>(src.width) * bytes_per_pixel(src.format);
    const size_t src_pitch = (src.pitch != 0) ? src.pitch : row_bytes;
    check_cuda(cudaMemcpy2DToArrayAsync(dst.cuda_array(),
                                        /*wOffset=*/0,
                                        /*hOffset=*/0, src.data, src_pitch, row_bytes, src.height,
                                        cudaMemcpyDeviceToDevice, stream),
               "cudaMemcpy2DToArrayAsync");
}

uint8_t ProjectionLayer::pick_free_slot() const noexcept
{
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    for (uint8_t s = 0; s < static_cast<uint8_t>(kSlotCount); ++s)
    {
        if (s == latest)
        {
            continue;
        }
        bool used = false;
        for (const auto& a : in_use_)
        {
            if (a.load(std::memory_order_acquire) == s)
            {
                used = true;
                break;
            }
        }
        if (!used)
        {
            return s;
        }
    }
    return kSlotNone;
}

void ProjectionLayer::submit(const VizBuffer& left_color,
                             const VizBuffer* left_depth,
                             const VizBuffer* right_color,
                             const VizBuffer* right_depth,
                             cudaStream_t stream)
{
    // ── Validate config / call shape ─────────────────────────────────
    validate_submit_buffer(left_color, config_.color_format, "submit(left_color)");

    const bool stereo = config_.stereo;
    if (stereo)
    {
        if (right_color == nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: stereo layer requires right_color");
        }
        validate_submit_buffer(*right_color, config_.color_format, "submit(right_color)");
    }
    else
    {
        if (right_color != nullptr || right_depth != nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: mono layer must not pass right buffers");
        }
    }

    if (has_depth_)
    {
        if (left_depth == nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: depth-enabled layer requires left_depth");
        }
        validate_submit_buffer(*left_depth, PixelFormat::kD32F, "submit(left_depth)");
        if (stereo)
        {
            if (right_depth == nullptr)
            {
                throw std::invalid_argument("ProjectionLayer: stereo + depth requires right_depth");
            }
            validate_submit_buffer(*right_depth, PixelFormat::kD32F, "submit(right_depth)");
        }
    }
    else
    {
        if (left_depth != nullptr || right_depth != nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: depth-disabled layer must not pass depth buffers");
        }
    }

    // ── Pick a free slot ─────────────────────────────────────────────
    const uint8_t slot = pick_free_slot();
    if (slot == kSlotNone)
    {
        // Should be unreachable given the kSlotCount invariant
        // (kMaxFramesInFlight + 2 ≥ worst-case forbidden set + 1).
        throw std::runtime_error("ProjectionLayer: no free mailbox slot — sizing invariant violated");
    }

    // ── Copy + signal ────────────────────────────────────────────────
    enqueue_copy(left_color, *slots_color_[slot][0], stream);
    if (has_depth_)
    {
        enqueue_copy(*left_depth, *slots_depth_[slot][0], stream);
    }
    if (stereo)
    {
        enqueue_copy(*right_color, *slots_color_[slot][1], stream);
        if (has_depth_)
        {
            enqueue_copy(*right_depth, *slots_depth_[slot][1], stream);
        }
    }

    // One semaphore signal per CUDA-mapped image we wrote. The compositor
    // waits on the in-use slot's set of cuda_done_writing values before
    // the backend copies them (get_wait_semaphores).
    slots_color_[slot][0]->cuda_signal_write_done(stream);
    if (has_depth_)
    {
        slots_depth_[slot][0]->cuda_signal_write_done(stream);
    }
    if (stereo)
    {
        slots_color_[slot][1]->cuda_signal_write_done(stream);
        if (has_depth_)
        {
            slots_depth_[slot][1]->cuda_signal_write_done(stream);
        }
    }

    // BLOCK on stream completion so the caller can re-use src buffers
    // immediately. Same contract as QuadLayer::submit. ~sub-ms cost.
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize");

    latest_.store(slot, std::memory_order_release);
    submitted_this_frame_.store(true, std::memory_order_release);
}

// ─── Frame state / direct present ────────────────────────────────────

void ProjectionLayer::on_frame_begin()
{
    // VizSession's begin_frame calls this on every layer. Clearing the
    // flag here means a layer that fails to submit between begin_frame and
    // end_frame is skipped (kXr) at acquire_direct_views() time.
    submitted_this_frame_.store(false, std::memory_order_release);
}

std::vector<LayerBase::WaitSemaphore> ProjectionLayer::get_wait_semaphores() const
{
    std::vector<WaitSemaphore> waits;
    const uint8_t cur = last_in_use_slot_.load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return waits;
    }
    const auto add = [&](const DeviceImage& img)
    {
        const uint64_t value = img.cuda_done_writing_value();
        if (value == 0)
        {
            return;
        }
        WaitSemaphore w{};
        w.semaphore = img.cuda_done_writing();
        w.value = value;
        // The backend copies these images (vkCmdCopyImage), so gate the
        // CUDA-done wait at the transfer stage, not the fragment stage.
        w.wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        waits.push_back(w);
    };
    for (uint32_t v = 0; v < view_count_; ++v)
    {
        if (slots_color_[cur].size() > v && slots_color_[cur][v])
        {
            add(*slots_color_[cur][v]);
        }
        if (has_depth_ && slots_depth_[cur].size() > v && slots_depth_[cur][v])
        {
            add(*slots_depth_[cur][v]);
        }
    }
    return waits;
}

std::vector<DirectPresentView> ProjectionLayer::acquire_direct_views(uint32_t in_flight_slot)
{
    if (in_flight_slot >= kMaxFramesInFlight)
    {
        throw std::logic_error("ProjectionLayer: in_flight_slot exceeds kMaxFramesInFlight");
    }

    const bool xr_mode = session() != nullptr && session()->is_xr_mode();
    const uint8_t latest = latest_.load(std::memory_order_acquire);

    // Freshness gate: in kXr never hand the runtime stale RGBD under this
    // frame's pose; nothing-published is the same skip. On skip leave no
    // in-use slot so get_wait_semaphores() is empty and the backend clears
    // the swapchains.
    const bool skip = latest == kSlotNone || (xr_mode && !submitted_this_frame_.load(std::memory_order_acquire));
    if (skip)
    {
        in_use_[in_flight_slot].store(kSlotNone, std::memory_order_release);
        last_in_use_slot_.store(kSlotNone, std::memory_order_release);
        return {};
    }

    // Promote the latest publish so get_wait_semaphores() waits on its
    // cuda_done_writing before the backend copies it.
    in_use_[in_flight_slot].store(latest, std::memory_order_release);
    last_in_use_slot_.store(latest, std::memory_order_release);

    std::vector<DirectPresentView> views;
    views.reserve(view_count_);
    for (uint32_t v = 0; v < view_count_; ++v)
    {
        DirectPresentView dv{};
        dv.extent = config_.view_resolution;
        if (slots_color_[latest].size() > v && slots_color_[latest][v])
        {
            dv.color = slots_color_[latest][v]->vk_image();
        }
        if (has_depth_ && slots_depth_[latest].size() > v && slots_depth_[latest][v])
        {
            dv.depth = slots_depth_[latest][v]->vk_image();
        }
        views.push_back(dv);
    }
    return views;
}

// ─── Accessors ───────────────────────────────────────────────────────

void ProjectionLayer::validate_backend_compatibility(Resolution recommended_view_resolution,
                                                     uint32_t backend_view_count,
                                                     uint32_t backend_image_count) const
{
    // Direct-present copies each view's image 1:1 into the swapchain, so the
    // source resolution must equal the backend's per-view size.
    if (config_.view_resolution.width != recommended_view_resolution.width ||
        config_.view_resolution.height != recommended_view_resolution.height)
    {
        throw std::invalid_argument(
            "ProjectionLayer: view_resolution (" + std::to_string(config_.view_resolution.width) + "x" +
            std::to_string(config_.view_resolution.height) + ") must equal the display's recommended per-view size (" +
            std::to_string(recommended_view_resolution.width) + "x" + std::to_string(recommended_view_resolution.height) +
            "); use VizSession::get_recommended_resolution() to size the layer.");
    }
    // A stereo display (kXr: 2 views) needs a layer that produces at least
    // that many views, else an eye would be left blank. A stereo layer in a
    // mono display is fine (the left eye is used).
    if (view_count_ < backend_view_count)
    {
        throw std::invalid_argument("ProjectionLayer: a mono layer cannot drive a " + std::to_string(backend_view_count) +
                                    "-view (stereo) display; construct with Config::stereo = true.");
    }
    // The per-frame in-use slot index is the backend's in-flight image index;
    // it must fit the mailbox. Fail here at attach rather than mid-frame.
    if (backend_image_count > kMaxFramesInFlight)
    {
        throw std::invalid_argument(
            "ProjectionLayer: backend cycles " + std::to_string(backend_image_count) +
            " in-flight images, exceeding kMaxFramesInFlight=" + std::to_string(kMaxFramesInFlight) + ".");
    }
}

Resolution ProjectionLayer::view_resolution() const noexcept
{
    return config_.view_resolution;
}

PixelFormat ProjectionLayer::color_format() const noexcept
{
    return config_.color_format;
}

std::optional<PixelFormat> ProjectionLayer::depth_format() const noexcept
{
    return config_.depth_format;
}

bool ProjectionLayer::is_stereo() const noexcept
{
    return config_.stereo;
}

uint32_t ProjectionLayer::view_count() const noexcept
{
    return view_count_;
}

const DeviceImage* ProjectionLayer::color_image(uint32_t slot, uint32_t view) const noexcept
{
    if (slot >= kSlotCount || view >= view_count_ || slots_color_[slot].size() <= view)
    {
        return nullptr;
    }
    return slots_color_[slot][view].get();
}

const DeviceImage* ProjectionLayer::depth_image(uint32_t slot, uint32_t view) const noexcept
{
    if (!has_depth_ || slot >= kSlotCount || view >= view_count_ || slots_depth_[slot].size() <= view)
    {
        return nullptr;
    }
    return slots_depth_[slot][view].get();
}

} // namespace viz
