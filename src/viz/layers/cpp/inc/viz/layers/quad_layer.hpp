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
#include <mutex>
#include <optional>
#include <string>

namespace viz
{

class VkContext;

// QuadLayer: renders a CUDA-fed RGBA8 texture, either fullscreen
// (window/offscreen — quad fills the layer's tile) or as a world-space
// rectangle (kXr — Config::placement required).
//
// Mailbox: kSlotCount DeviceImages. submit() picks a slot that's
// neither the latest publish nor in use by any in-flight frame, copies
// pixels in, signals cuda_done_writing, and atomic-stores latest.
// record(slot_index) atomic-stores latest into in_use_[slot_index]
// and draws. Producer never collides with the slot any in-flight
// renderer is sampling; renderer always sees the most recent
// completed publish.
//
// Sizing invariant: kSlotCount = kMaxFramesInFlight + 2. Worst-case
// forbidden set is {latest} ∪ in_use_ → 1 + kMaxFramesInFlight distinct
// values, the +2 leaves at least one free slot. If a backend's
// image_count ever exceeds kMaxFramesInFlight, record() asserts —
// bump kMaxFramesInFlight and kSlotCount together.
//
// Memory: kSlotCount × width × height × bpp.
//   mono   1080p RGBA8: ~56 MB / layer
//   mono   4K    RGBA8: ~232 MB / layer
//   stereo 1080p RGBA8: ~112 MB / layer (×2 from paired slots)
//   stereo 4K    RGBA8: ~464 MB / layer
// With ``generate_mipmaps`` on (default), add ~33% for the mip chain.
// A single 4K stereo layer with mips is ~620 MB — sizing concern for
// the host's VRAM budget and worth surfacing to whoever picks the
// resolution / layer count.
//
// Stereo: when Config::stereo is true, each slot owns a PAIR of
// DeviceImages (left + right). The two-arg submit() does both
// memcpy2Ds + the cuda_done_writing signal on a single CUDA stream,
// so stream ordering guarantees the renderer never sees a half-
// updated pair. In kXr, record() binds the left descriptor for
// view 0 and the right for view 1; window/offscreen (single view)
// draws the left buffer only.
class QuadLayer : public LayerBase
{
public:
    // Sized to cover swapchains up to 5 images. The window swapchain
    // requests <= 3 (see Swapchain::init), but drivers may grant more
    // than requested; this headroom keeps record() from throwing on
    // those platforms. Memory cost: kSlotCount × W × H × bpp per layer
    // (~56 MB at 1080p RGBA8).
    static constexpr uint32_t kMaxFramesInFlight = 5;
    static constexpr uint32_t kSlotCount = kMaxFramesInFlight + 2;

    struct Config
    {
        std::string name = "QuadLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;

        // 3D placement in the session's reference space (OpenXR LOCAL
        // or STAGE). size_meters is width × height; both components
        // must be > 0 (validated at construction).
        struct Placement
        {
            Pose3D pose{};
            glm::vec2 size_meters{ 0.0f, 0.0f };
        };

        // window/offscreen ignore this. kXr REQUIRES it: stretching a
        // fullscreen quad across stereo eyes is never the right thing.
        // record() throws std::logic_error on kXr + nullopt.
        std::optional<Placement> placement;

        // Allocate a small mip chain on each DeviceImage slot and
        // regenerate it via vkCmdBlitImage in record_pre_render_pass.
        // Sampler switches to LINEAR mip filtering. Capped internally
        // at kMaxMipLevels (smallest level is 1/8 linear dims for the
        // typical 1080p / 4K source) — past that the cost outpaces the
        // visual win for our XR distance-view use cases.
        // On by default: the per-frame cost is sub-millisecond and the
        // aliasing it removes is very visible in XR / multi-tile grids.
        // Set to false to save the ~33% extra image memory on layers
        // that are always sampled at native resolution.
        bool generate_mipmaps = true;

        // Stereo mode. When true, the layer owns a paired left+right
        // mailbox; submit MUST be called with both buffers. In kXr,
        // view 0 (left eye) samples the left buffer and view 1 (right
        // eye) the right. In window/offscreen the left buffer is drawn
        // and the right is allocated but unused. Memory doubles.
        bool stereo = false;

        // Horizontal disparity between the left-plane (in the left eye)
        // and the right-plane (in the right eye), in millimeters along
        // the placement's local +x axis. Each eye's quad center is
        // shifted by ±stereo_baseline_mm/2 (left eye: −, right eye: +).
        // 0 means both eyes see the same world-space quad; all stereo
        // cues come from the captured images. Positive values let the
        // planes splay outward (virtual screen further back); negative
        // makes them cross (closer to viewer). Ignored when stereo is
        // false or outside kXr. mm-scale chosen because typical real-
        // world IPDs and camera baselines are 50–80 mm.
        float stereo_baseline_mm = 0.0f;
    };

    // Hard cap on the mip chain when generate_mipmaps is enabled.
    // Smallest level is 1/(2^(kMaxMipLevels-1)) of the linear extent;
    // at 4 that's 1/8 (240x135 from 1080p, 480x270 from 4K).
    static constexpr uint32_t kMaxMipLevels = 4;

    // Builds the 3 DeviceImages + pipeline up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config);

    ~QuadLayer() override;
    void destroy();

    // submit() = producer side, record() = consumer side; may run on
    // separate threads. NOT safe with multiple concurrent producers
    // (one QuadLayer per producer).
    //
    // src.space must be kDevice; dims/format must match the layer.
    // The copy + cuda_done_writing signal run on ``stream``. submit()
    // BLOCKS on cudaStreamSynchronize(stream) before returning so the
    // producer can safely reuse src.data — without that wait, a fast
    // producer wrapping its mailbox could overwrite src.data while our
    // async memcpy was still reading. Cost: ~0.5 ms per 1080p call on
    // the calling thread; the render path is unaffected.
    //
    // Mono layer (Config::stereo == false): use the one-arg overload.
    // The two-arg overload throws std::logic_error.
    //
    // Stereo layer (Config::stereo == true): use the two-arg overload.
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

    // Pre-pass slot: promote latest_ -> in_use_[in_flight_slot] AND
    // (when generate_mipmaps is on) emit the mip-chain blits on the
    // in-use slot. record() reads the already-promoted slot, so both
    // calls must agree on in_flight_slot for the same frame.
    void record_pre_render_pass(VkCommandBuffer cmd, uint32_t in_flight_slot) override;

    // Skips the draw before the first submit (slot kSlotNone) — RT
    // keeps its clear value. in_flight_slot identifies which of the
    // up to kMaxFramesInFlight in-flight frames is being recorded;
    // this slot's in_use_ entry is updated to the current latest_.
    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target,
                uint32_t in_flight_slot) override;

    // Timeline wait on the in-use slot's cuda_done_writing.
    std::vector<LayerBase::WaitSemaphore> get_wait_semaphores() const override;

    // Drives aspect-fit letterbox in window mode; ignored in kXr.
    std::optional<float> aspect_ratio() const noexcept override;

    Resolution resolution() const noexcept;
    PixelFormat format() const noexcept;

    // Atomic placement swap, thread-safe vs record(). nullopt switches
    // to fullscreen mode (kXr will throw on next record).
    void set_placement(std::optional<Config::Placement> placement) noexcept;
    std::optional<Config::Placement> placement() const noexcept;

    // Diagnostic accessor; nullptr for slots beyond kSlotCount, and
    // device_image_right is null on mono layers.
    const DeviceImage* device_image(uint32_t slot) const noexcept;
    const DeviceImage* device_image_right(uint32_t slot) const noexcept;

private:
    void init();

    void create_sampler();
    void create_descriptor_set_layout();
    void create_pipeline_layout();
    void create_pipeline();
    void create_descriptor_pool();
    void allocate_descriptor_sets();
    void update_descriptor_sets();

    // Mailbox slot allocation. submit() picks one of these states
    // and atomically takes ownership; record() atomically promotes
    // a freshly-published slot to `in_use_`.
    static constexpr uint8_t kSlotNone = 0xFF;

    // Picks a slot that is neither latest_ nor in any in_use_ entry.
    // Returns kSlotNone if every slot is forbidden (producer outran the
    // renderer beyond the sizing invariant) — caller drops the publish.
    uint8_t pick_free_slot(uint8_t latest,
                           const std::array<std::atomic<uint8_t>, kMaxFramesInFlight>& in_use) const noexcept;

    // Emit a full mip-chain regeneration for ``image`` via
    // vkCmdBlitImage. Assumes the image is currently in
    // VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL and returns it to the
    // same layout. Only called when Config::generate_mipmaps is true.
    void record_mip_generation(VkCommandBuffer cmd, DeviceImage& image);

    const VkContext* ctx_ = nullptr;
    VkRenderPass render_pass_ = VK_NULL_HANDLE; // borrowed from compositor
    Config config_;
    // Number of mip levels per DeviceImage slot. 1 when mips disabled.
    uint32_t mip_levels_ = 1;

    // One DeviceImage per mailbox slot. ``slots_`` is the left/mono
    // image; ``slots_right_`` only allocated when Config::stereo.
    std::array<std::unique_ptr<DeviceImage>, kSlotCount> slots_;
    std::array<std::unique_ptr<DeviceImage>, kSlotCount> slots_right_;

    VkSampler sampler_ = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout_ = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;

    VkDescriptorPool descriptor_pool_ = VK_NULL_HANDLE;
    // One descriptor set per slot — record() binds the one for in_use_.
    // ``descriptor_sets_right_`` is only populated when Config::stereo.
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_{};
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_right_{};

    // Mailbox: latest_ = most recent publish. in_use_[i] = slot the
    // i-th in-flight frame is sampling. Atomic so producer and
    // renderer share without locks. All kSlotNone until first
    // submit() / first sampling record(). Both record() and
    // get_wait_semaphores() use the LAST seen in_use_ slot (any
    // entry — record updates one, get_wait_semaphores reads from
    // whichever entry corresponds to the in-flight frame that just
    // recorded).
    std::atomic<uint8_t> latest_{ kSlotNone };
    std::array<std::atomic<uint8_t>, kMaxFramesInFlight> in_use_{};
    // Tracks which in_use_ entry was MOST RECENTLY promoted by
    // record(). get_wait_semaphores() reads this entry's slot — it's
    // the one whose cuda_done_writing semaphore gates the GPU's
    // sampling work that was just queued. Atomic but doesn't need
    // mutual exclusion with in_use_ stores (the renderer thread does
    // both writes; we use atomics for cross-thread visibility with
    // submit's reads in pick_free_slot).
    std::atomic<uint8_t> last_in_use_slot_{ kSlotNone };

    // Live placement; lock for set_placement / record() snapshot.
    mutable std::mutex placement_mutex_;
    std::optional<Config::Placement> placement_;
};

} // namespace viz
