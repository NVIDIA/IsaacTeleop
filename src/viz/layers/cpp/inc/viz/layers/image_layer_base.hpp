// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/session/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <cuda_runtime.h>
#include <memory>
#include <string>

namespace viz
{

class VkContext;

// Shared base for layers whose content is a CUDA-fed RGBA8 texture
// (QuadLayer, CylinderLayer, EquirectLayer): owns the DeviceImage
// mailbox and the producer/consumer protocol; subclasses decide how the
// texture is composited (draw call into the shared RT, or a native
// OpenXR composition layer).
//
// Mailbox: kSlotCount DeviceImages. submit() picks a slot that's
// neither the latest publish nor in use by any in-flight frame, copies
// pixels in, signals cuda_done_writing, and atomic-stores latest.
// The consumer (promote_slot) atomic-stores latest into
// in_use_[in_flight_slot] and samples/copies it. Producer never
// collides with the slot any in-flight renderer is reading; renderer
// always sees the most recent completed publish.
//
// Sizing invariant: kSlotCount = kMaxFramesInFlight + 2. Worst-case
// forbidden set is {latest} ∪ in_use_ → 1 + kMaxFramesInFlight distinct
// values, the +2 leaves at least one free slot. If a backend's
// image_count ever exceeds kMaxFramesInFlight, promote_slot throws —
// bump kMaxFramesInFlight and kSlotCount together.
//
// Memory: kSlotCount × width × height × bpp (× mip overhead when the
// subclass requests a mip chain, ×2 when stereo).
//   mono   1080p RGBA8: ~56 MB / layer
//   mono   4K    RGBA8: ~232 MB / layer
//   stereo 1080p RGBA8: ~112 MB / layer (×2 from paired slots)
//   stereo 4K    RGBA8: ~464 MB / layer
//
// Stereo: when ``stereo`` is true, each slot owns a PAIR of
// DeviceImages (left + right). The two-arg submit() does both
// memcpy2Ds + the cuda_done_writing signal on a single CUDA stream,
// so stream ordering guarantees the renderer never sees a half-
// updated pair.
class ImageLayerBase : public LayerBase
{
public:
    // Sized to cover swapchains up to 5 images. The window swapchain
    // requests <= 3 (see Swapchain::init), but drivers may grant more
    // than requested; this headroom keeps promote_slot from throwing on
    // those platforms. Memory cost: kSlotCount × W × H × bpp per layer
    // (~56 MB at 1080p RGBA8).
    static constexpr uint32_t kMaxFramesInFlight = 5;
    static constexpr uint32_t kSlotCount = kMaxFramesInFlight + 2;

    // submit() = producer side, promote_slot() = consumer side; may run
    // on separate threads. NOT safe with multiple concurrent producers
    // (one layer per producer).
    //
    // src.space must be kDevice; dims/format must match the layer.
    // The copy + cuda_done_writing signal run on ``stream``. submit()
    // BLOCKS on cudaStreamSynchronize(stream) before returning so the
    // producer can safely reuse src.data — without that wait, a fast
    // producer wrapping its mailbox could overwrite src.data while our
    // async memcpy was still reading. Cost: ~0.5 ms per 1080p call on
    // the calling thread; the render path is unaffected.
    //
    // Mono layer (stereo == false): use the one-arg overload.
    // The two-arg overload throws std::logic_error.
    //
    // Stereo layer (stereo == true): use the two-arg overload.
    // Both buffers are copied + the single cuda_done_writing signal is
    // emitted on the SAME ``stream``, so stream ordering guarantees
    // the renderer never reads a half-matched pair. The one-arg
    // overload throws std::logic_error.
    //
    // STREAM PRECONDITION (stereo): the two-arg overload runs the copies
    // for BOTH eyes on the single ``stream`` argument. CUDA's stream
    // ordering only sequences work submitted to the SAME stream, so
    // when ``left.data`` or ``right.data`` was produced on a different
    // stream than ``stream``, the caller MUST synchronize that producer
    // stream before calling submit (cudaStreamSynchronize, or a recorded
    // event waited on ``stream`` via cudaStreamWaitEvent). Otherwise the
    // memcpy here can read stale / torn pixels for that eye. The
    // in-tree ZED + OAK-D producers handle this by calling
    // ``cu_stream.synchronize()`` per eye-slot before publishing, which
    // makes calling ``submit(left, right, stream=0)`` safe; external
    // producers wiring separate per-eye streams must follow the same
    // pattern.
    void submit(const VizBuffer& src, cudaStream_t stream = 0);
    void submit(const VizBuffer& left, const VizBuffer& right, cudaStream_t stream = 0);

    // Timeline wait on the in-use slot's cuda_done_writing, at the
    // subclass's first_read_stage().
    std::vector<LayerBase::WaitSemaphore> get_wait_semaphores() const override;

    const VkContext* vk_context() const noexcept override
    {
        return ctx_;
    }

    Resolution resolution() const noexcept
    {
        return resolution_;
    }
    PixelFormat format() const noexcept
    {
        return format_;
    }
    bool stereo() const noexcept
    {
        return stereo_;
    }

    // Diagnostic accessor; nullptr for slots beyond kSlotCount, and
    // device_image_right is null on mono layers.
    const DeviceImage* device_image(uint32_t slot) const noexcept;
    const DeviceImage* device_image_right(uint32_t slot) const noexcept;

protected:
    // Validates + allocates the mailbox images up front. ``layer_type``
    // prefixes error messages (e.g. "QuadLayer"). Throws
    // std::invalid_argument on bad parameters; std::runtime_error on
    // Vulkan / CUDA failure (nothing leaks — DeviceImages are RAII).
    ImageLayerBase(const VkContext& ctx,
                   std::string layer_type,
                   std::string name,
                   Resolution resolution,
                   PixelFormat format,
                   bool stereo,
                   uint32_t mip_levels);

    // Subclass dtors/destroy() call destroy_images(); the base dtor
    // covers subclasses without an explicit destroy.
    ~ImageLayerBase() override;

    // Mailbox slot allocation. submit() picks one of these states
    // and atomically takes ownership; promote_slot atomically promotes
    // a freshly-published slot to `in_use_`.
    static constexpr uint8_t kSlotNone = 0xFF;

    // Releases every DeviceImage and resets the mailbox to its initial
    // state. Idempotent; safe after partial subclass init.
    void destroy_images();

    // Once destroy has run, slots_[0] is the canonical "alive" signal.
    // Throwing logic_error converts use-after-destroy from a silent
    // null-deref into a clean failure callers can catch in tests.
    void require_alive(const char* what) const;

    // Promote latest_ -> in_use_[in_flight_slot] and update
    // last_in_use_slot_ (shared by the render-pass consumer and the
    // native-layer consumer). Returns the promoted slot, or kSlotNone if
    // nothing has been published yet. Throws if in_flight_slot is out of
    // range. Renderer thread only.
    uint8_t promote_slot(uint32_t in_flight_slot);

    // Slot already promoted for ``in_flight_slot`` this frame (kSlotNone
    // before any publish, or for an out-of-range slot). Read-only view of
    // the mailbox for subclass consumers that promote in one hook and
    // consume in another (QuadLayer's pre-pass / record split).
    uint8_t promoted_slot(uint32_t in_flight_slot) const noexcept;

    // First pipeline stage that reads the promoted image in the frame's
    // command buffer — threads into the queue submit's cuda_done_writing
    // wait. Default TRANSFER (native composition copies the image);
    // QuadLayer's draw path overrides with FRAGMENT_SHADER when the
    // sampler is the first reader.
    virtual VkPipelineStageFlags first_read_stage() const noexcept
    {
        return VK_PIPELINE_STAGE_TRANSFER_BIT;
    }

    const VkContext* ctx_ = nullptr;

    // One DeviceImage per mailbox slot. ``slots_`` is the left/mono
    // image; ``slots_right_`` only allocated when stereo.
    std::array<std::unique_ptr<DeviceImage>, kSlotCount> slots_;
    std::array<std::unique_ptr<DeviceImage>, kSlotCount> slots_right_;

private:
    // Picks a slot that is neither latest_ nor in any in_use_ entry.
    // Returns kSlotNone if every slot is forbidden (producer outran the
    // renderer beyond the sizing invariant) — caller drops the publish.
    uint8_t pick_free_slot(uint8_t latest) const noexcept;

    void validate_submit_buffer(const VizBuffer& buf, const char* label) const;

    std::string layer_type_;
    Resolution resolution_{};
    PixelFormat format_ = PixelFormat::kRGBA8;
    bool stereo_ = false;

    // Mailbox: latest_ = most recent publish. in_use_[i] = slot the
    // i-th in-flight frame is sampling. Atomic so producer and
    // renderer share without locks. All kSlotNone until first
    // submit() / first consumer promote.
    std::atomic<uint8_t> latest_{ kSlotNone };
    std::array<std::atomic<uint8_t>, kMaxFramesInFlight> in_use_{};
    // Tracks which in_use_ entry was MOST RECENTLY promoted.
    // get_wait_semaphores() reads this entry's slot — it's the one whose
    // cuda_done_writing semaphore gates the GPU's read work that was
    // just queued. Atomic but doesn't need mutual exclusion with
    // in_use_ stores (the renderer thread does both writes; we use
    // atomics for cross-thread visibility with submit's reads in
    // pick_free_slot).
    std::atomic<uint8_t> last_in_use_slot_{ kSlotNone };
};

} // namespace viz
