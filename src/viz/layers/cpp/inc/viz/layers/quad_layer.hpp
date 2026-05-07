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
// Mailbox: kSlotCount=3 DeviceImages. submit() picks a slot that's
// neither the latest publish nor in use, copies pixels in, signals
// cuda_done_writing, and atomic-exchanges latest. record() exchanges
// latest into in_use and draws, waiting on the slot's semaphore.
// Producer never collides with the slot the renderer is sampling;
// renderer always sees the most recent completed publish.
//
// Correctness depends on VizCompositor::render() being synchronous
// (single frame in flight). Multi-frame would need per-frame in_use.
//
// Memory: ~3 × width × height × bpp (24 MB at 1080p RGBA8).
class QuadLayer : public LayerBase
{
public:
    static constexpr uint32_t kSlotCount = 3;

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
    // keeps its clear value.
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& target) override;

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

    // Picks a slot that is neither latest_ nor in_use_, in
    // 0..kSlotCount-1. Returns a value < kSlotCount.
    uint8_t pick_free_slot(uint8_t latest, uint8_t in_use) const noexcept;

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

    // Mailbox: latest_ = most recent publish, in_use_ = slot the renderer
    // is sampling. Atomic so producer and renderer share without locks.
    // Both kSlotNone until the first submit() / first sampling record().
    std::atomic<uint8_t> latest_{ kSlotNone };
    std::atomic<uint8_t> in_use_{ kSlotNone };

    // Live placement; lock for set_placement / record() snapshot.
    mutable std::mutex placement_mutex_;
    std::optional<Config::Placement> placement_;
};

} // namespace viz
