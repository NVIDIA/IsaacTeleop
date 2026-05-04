// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp> // Resolution, VizCudaArray
#include <viz/layers/layer_base.hpp>
#include <vulkan/vulkan.h>

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
// Sync today is heavyweight (vkDeviceWaitIdle + cudaDeviceSynchronize
// inside submit / release). Fullscreen-blit / kRGBA8 only — placement
// and other formats land with the XR backend.
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

    // Mode A: copy caller's CUDA buffer into our DeviceImage.
    // src.space must be kDevice and dimensions must match the
    // layer's resolution. Synchronous; throws on validation failure.
    void submit(const VizBuffer& src);

    // Mode B: returns a VizCudaArray view onto the layer's tiled
    // CUDA memory for the caller to write directly. Valid until
    // the next acquire / release / destroy. release() syncs both
    // sides before returning.
    VizCudaArray acquire();
    void release();

    // Binds pipeline + descriptor + draws a 3-vertex fullscreen quad.
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& target) override;

    Resolution resolution() const noexcept;
    PixelFormat format() const noexcept;
    const DeviceImage* device_image() const noexcept
    {
        return device_image_.get();
    }

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
};

} // namespace viz
