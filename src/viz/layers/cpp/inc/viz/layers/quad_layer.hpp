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
// Mailbox: kSlotCount=4 DeviceImages. submit() picks a slot that's
// neither the latest publish nor in use by any in-flight frame, copies
// pixels in, signals cuda_done_writing, and atomic-stores latest.
// record(slot_index) atomic-stores latest into in_use_[slot_index]
// and draws. Producer never collides with the slot any in-flight
// renderer is sampling; renderer always sees the most recent
// completed publish.
//
// Multi-frame-in-flight: VizCompositor passes the in-flight slot index
// to record(); we keep one in_use_ entry per slot so submit's
// pick_free_slot can exclude all the slots that any active GPU work is
// reading. With 4 storage slots and at most {latest + 3 in_use}
// distinct forbidden values, there's always at least one free slot.
//
// Memory: ~4 × width × height × bpp (32 MB at 1080p RGBA8).
class QuadLayer : public LayerBase
{
public:
    // 4 storage slots: 1 for latest, up to 3 in-flight frames'
    // in_use_ entries, leaves at least 1 free for the next submit.
    static constexpr uint32_t kSlotCount = 4;
    // Matches typical swapchain image count. Compositor's slot index
    // is taken modulo this when indexing in_use_; the array sized to
    // this dimension regardless of actual backend image_count keeps
    // pick_free_slot O(1) and lets the same QuadLayer attach to any
    // backend without re-allocating.
    static constexpr uint32_t kMaxFramesInFlight = 3;

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
    };

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
    // The copy + cuda_done_writing signal run on `stream` — pass the
    // producer's stream so the signal lands after its prior writes.
    void submit(const VizBuffer& src, cudaStream_t stream = 0);

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

    // Diagnostic accessor; nullptr for slots beyond kSlotCount.
    const DeviceImage* device_image(uint32_t slot) const noexcept;

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

    // Picks a slot that is neither latest_ nor in any in_use_ entry,
    // in 0..kSlotCount-1. With kSlotCount=4 and at most
    // (1 + kMaxFramesInFlight) = 4 forbidden values, the worst case
    // still leaves zero free — but in steady state the most-recent
    // in_use_ entry equals latest_, so typically 2-3 distinct
    // forbidden values and 1-2 free slots.
    uint8_t pick_free_slot(uint8_t latest,
                           const std::array<std::atomic<uint8_t>, kMaxFramesInFlight>& in_use) const noexcept;

    const VkContext* ctx_ = nullptr;
    VkRenderPass render_pass_ = VK_NULL_HANDLE; // borrowed from compositor
    Config config_;

    // One DeviceImage per mailbox slot.
    std::array<std::unique_ptr<DeviceImage>, kSlotCount> slots_;

    VkSampler sampler_ = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout_ = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;

    VkDescriptorPool descriptor_pool_ = VK_NULL_HANDLE;
    // One descriptor set per slot — record() binds the one for in_use_.
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_{};

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
