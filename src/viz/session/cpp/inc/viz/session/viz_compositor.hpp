// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/frame_sync.hpp>
#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <memory>
#include <vector>

namespace viz
{

class LayerBase;
class VkContext;

// VizCompositor: the per-session GPU pipeline that runs one render pass
// per frame. Owns the intermediate RenderTarget, command pool / buffer,
// and FrameSync. Iterates a layer registry (held by VizSession) calling
// each visible layer's record() inside the active render pass, then
// submits to the queue.
//
// Lifetime: owned by VizSession. Created when the session moves from
// kUninitialized to kReady; destroyed when the session is destroyed.
class VizCompositor
{
public:
    struct Config
    {
        Resolution resolution{};
        VkClearColorValue clear_color{ { 0.0f, 0.0f, 0.0f, 1.0f } };
    };

    static std::unique_ptr<VizCompositor> create(const VkContext& ctx, const Config& config);

    ~VizCompositor();
    void destroy();

    VizCompositor(const VizCompositor&) = delete;
    VizCompositor& operator=(const VizCompositor&) = delete;
    VizCompositor(VizCompositor&&) = delete;
    VizCompositor& operator=(VizCompositor&&) = delete;

    // Records and submits one frame. Iterates `layers` (insertion order),
    // skipping invisible ones, calling layer->record() inside the active
    // render pass. Blocks on the previous frame's fence before recording
    // and on the new fence before returning (1-frame-in-flight today).
    //
    // Throws std::runtime_error on Vulkan failure.
    void render(const std::vector<LayerBase*>& layers, const std::vector<ViewInfo>& views);

    // Read the most recent frame's color attachment back to a host buffer.
    // Returns tightly-packed RGBA8 bytes (width * height * 4). The session
    // is expected to have called render() at least once; pixels are
    // undefined otherwise. Used by tests / debug tooling — production
    // (CUDA-pointer) readback lands with CUDA-Vulkan interop.
    std::vector<uint8_t> readback_to_host();

    // Accessors for layers / external code that needs to build pipelines
    // against the compositor's render pass.
    VkRenderPass render_pass() const noexcept;
    Resolution resolution() const noexcept;

private:
    VizCompositor(const VkContext& ctx, const Config& config);
    void init();

    void create_command_pool();
    void create_command_buffer();

    const VkContext* ctx_ = nullptr;
    Config config_{};

    std::unique_ptr<RenderTarget> render_target_;
    std::unique_ptr<FrameSync> frame_sync_;

    VkCommandPool command_pool_ = VK_NULL_HANDLE;
    VkCommandBuffer command_buffer_ = VK_NULL_HANDLE;
};

} // namespace viz
