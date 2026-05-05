// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp> // Resolution, VizCudaArray
#include <viz/layers/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <cstdint>
#include <cuda_runtime.h>
#include <memory>
#include <string>

namespace viz
{

class VkContext;

// QuadLayer: renders a CUDA-fed 2D texture as a fullscreen quad.
// Owns a DeviceImage and the graphics-pipeline state to sample it
// (VkSampler, descriptor set, VkPipeline using textured_quad
// shaders). Must be created against the compositor's render pass.
//
// Two ways to feed pixels in:
//   - submit(VizBuffer):       Mode A. We copy the caller's CUDA
//                              buffer into our DeviceImage.
//   - acquire() / release():   Mode B. Caller writes our tiled
//                              CUDA memory directly. Zero copy.
//
// Producer / consumer sync uses the timeline semaphores DeviceImage
// owns: submit / acquire / release queue async waits + signals on a
// caller-provided cudaStream_t; VizCompositor waits on the cuda
// signal before sampling and signals back when sampling is done.
// No host-side blocking. Fullscreen-blit / kRGBA8 only — placement
// transforms and other formats land with the XR backend.
class QuadLayer : public LayerBase
{
public:
    struct Config
    {
        std::string name = "QuadLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;
    };

    // Builds DeviceImage + pipeline up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config);

    ~QuadLayer() override;
    void destroy();

    // Threading contract for the producer-side methods (submit,
    // acquire, release): they MUST be called sequentially from a
    // single producer thread. Mixing producers (multiple cameras
    // feeding the SAME layer from different threads) is undefined —
    // use multiple QuadLayers, one per producer, instead.
    //
    // The producer thread may run concurrently with the render
    // thread that calls record(): the cross-thread coordination on
    // `acquired_` (atomic) gates record() so it never samples a
    // half-written DeviceImage. The atomic store from the producer
    // synchronizes with the atomic load from the renderer.

    // Mode A: copy caller's CUDA buffer into our DeviceImage.
    // src.space must be kDevice and dimensions must match the
    // layer's resolution. The wait/copy/signal sequence runs on
    // `stream` (default: the default stream); pass the producer's
    // stream so the signal is correctly ordered after the producer's
    // writes.
    // Throws std::invalid_argument on validation failure;
    // std::logic_error if Mode B is currently in flight.
    void submit(const VizBuffer& src, cudaStream_t stream = 0);

    // Mode B: returns a VizCudaArray view onto the layer's tiled
    // CUDA memory for the caller to write directly. The caller MUST
    // call release() (on the same stream they wrote on) before the
    // next render() / submit() / acquire().
    // Throws std::logic_error if a previous acquire() hasn't been
    // released yet (call on a single producer thread).
    VizCudaArray acquire(cudaStream_t stream = 0);

    // Pair of acquire(); signals cuda_done_writing on `stream` so
    // anything queued there before this call (the caller's writes)
    // is flushed before Vulkan samples.
    // Throws std::logic_error if no acquire() is in flight.
    void release(cudaStream_t stream = 0);

    // Binds pipeline + descriptor + draws a 3-vertex fullscreen quad.
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& target) override;

    // Compositor's submit waits on cuda_done_writing (CUDA must
    // finish writing the texture before the fragment shader samples
    // it) and signals vk_done_reading (so the next CUDA write knows
    // sampling is done). reserve_*_semaphores() reserves a value;
    // commit_pending_signals() finalizes it after vkQueueSubmit
    // succeeds (so a failed submit doesn't poison the timeline).
    std::vector<LayerBase::WaitSemaphore> get_wait_semaphores() const override;
    std::vector<LayerBase::SignalSemaphore> get_signal_semaphores() override;
    void commit_pending_signals() override;

    Resolution resolution() const noexcept;
    PixelFormat format() const noexcept;
    const DeviceImage* device_image() const noexcept
    {
        return device_image_.get();
    }

    // Producer-side state machine. submit() transitions
    //   kIdle -> kSubmitting -> kIdle (RAII guard).
    // acquire() transitions kIdle -> kAcquired; release() returns
    //   to kIdle. record() (on the render thread) rejects unless
    //   the state is kIdle, so a Mode A submit in flight or a Mode B
    //   acquire-without-release can't race with sampling.
    // Single producer thread (CAS on transitions catches misuse on
    // that thread), multiple readers (render thread loads with
    // acquire ordering).
    enum class ProducerState : std::uint8_t
    {
        kIdle = 0,
        kSubmitting,
        kAcquired,
    };

private:
    void init();

    void create_sampler();
    void create_descriptor_set_layout();
    void create_pipeline_layout();
    void create_pipeline();
    void create_descriptor_pool();
    void allocate_descriptor_set();
    void update_descriptor_set();

    const VkContext* ctx_ = nullptr;
    VkRenderPass render_pass_ = VK_NULL_HANDLE; // borrowed from compositor
    Config config_;

    std::unique_ptr<DeviceImage> device_image_;

    VkSampler sampler_ = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout_ = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;
    VkDescriptorPool descriptor_pool_ = VK_NULL_HANDLE;
    VkDescriptorSet descriptor_set_ = VK_NULL_HANDLE; // freed with the pool

    std::atomic<ProducerState> producer_state_{ ProducerState::kIdle };

    // Reserved-but-not-yet-committed signal value the compositor's
    // submit will signal vk_done_reading with. Captured by
    // get_signal_semaphores() and committed by
    // commit_pending_signals() when vkQueueSubmit succeeds.
    uint64_t pending_vk_signal_value_ = 0;
};

} // namespace viz
