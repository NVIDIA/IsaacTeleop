// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/layers/layer_base.hpp>
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

// QuadLayer: renders a CUDA-fed 2D texture as a fullscreen quad.
//
// Owns kSlotCount=3 DeviceImages plus the graphics-pipeline state to
// sample any of them (one VkSampler, one VkPipeline, one descriptor
// set per slot). The slots form a mailbox:
//
//   submit() picks a "free" slot (one that is neither the most recent
//   publish nor the slot the renderer is currently sampling), runs
//   cudaMemcpyAsync into it, signals cuda_done_writing, and atomic-
//   exchanges the "latest" pointer to it. The previous "latest" slot
//   becomes free.
//
//   record() atomic-exchanges "latest" into "in_use" (taking it for
//   this frame's draw); the previous "in_use" slot becomes free. The
//   draw waits on cuda_done_writing of the slot it just took.
//
// Net result: producer can submit at any rate. The renderer always
// samples the most recently completed publish, and there is always
// at least one slot free for the producer to write — it never
// collides with a buffer the renderer is currently sampling.
//
// Correctness depends on VizCompositor::render() being synchronous
// (frame_sync_->wait() at end of frame). Multi-frame-in-flight
// would require in_use_ to become per-in-flight-frame.
//
// Memory cost: ~width*height*bpp*3 bytes (e.g. 24 MB at 1080p RGBA8).
//
// Fullscreen-blit / kRGBA8 only. Placement transforms and other
// formats land with the XR backend.
class QuadLayer : public LayerBase
{
public:
    static constexpr uint32_t kSlotCount = 3;

    struct Config
    {
        std::string name = "QuadLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;
    };

    // Builds the 3 DeviceImages + pipeline up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config);

    ~QuadLayer() override;
    void destroy();

    // Threading contract: submit() is the producer side; record() (+
    // get_wait_semaphores) is the consumer side. They may run on
    // separate threads. Multiple concurrent producers on the same
    // QuadLayer are NOT supported — use one QuadLayer per producer.
    //
    // src.space must be kDevice and src dimensions/format must match
    // the layer. The wait/copy/signal sequence runs on `stream`
    // (default: the default stream); pass the producer's stream so
    // the signal lands after the producer's prior writes on the same
    // stream.
    //
    // Throws std::invalid_argument on validation failure;
    // std::runtime_error on CUDA failure;
    // std::logic_error if called after destroy().
    void submit(const VizBuffer& src, cudaStream_t stream = 0);

    // Binds pipeline + per-slot descriptor + draws a 3-vertex
    // fullscreen quad. Skips the draw if no frame has been published
    // yet (kSlotNone — render target keeps its clear value).
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& target) override;

    // Layer-side timeline wait: VizCompositor waits on this slot's
    // cuda_done_writing before the fragment shader samples it.
    std::vector<LayerBase::WaitSemaphore> get_wait_semaphores() const override;

    Resolution resolution() const noexcept;
    PixelFormat format() const noexcept;

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
    // One descriptor set per slot, each binding the corresponding
    // DeviceImage's sRGB view. record() picks the one for in_use_.
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_{};

    // Mailbox state. Both atomic so producer and renderer can
    // touch them without locks.
    //
    //   latest_:    most recently published slot. submit() stores
    //               here on success; record() exchanges it into
    //               in_use_ at frame start. kSlotNone before the
    //               first submit().
    //   in_use_:    slot the renderer is currently drawing from.
    //               kSlotNone before the first frame that finds a
    //               published slot. record() updates this.
    std::atomic<uint8_t> latest_{ kSlotNone };
    std::atomic<uint8_t> in_use_{ kSlotNone };
};

} // namespace viz
