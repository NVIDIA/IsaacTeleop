// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/layers/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <vector>

namespace viz::testing
{

// Test fixture layer: clears a rectangular region of the active
// framebuffer to a configured RGBA color via vkCmdClearAttachments.
//
// Used to verify the compositor's layer-dispatch + render-pass plumbing
// without bringing in shaders, graphics pipelines, or vertex buffers
// (those land with the first real graphics layer alongside CUDA-Vulkan
// interop). Exercises the same in-pass command-recording surface that
// real layers use.
//
// Coordinates are in framebuffer pixels with origin top-left; w/h
// default to the full target if both are zero.
class ClearRectLayer final : public LayerBase
{
public:
    struct Config
    {
        int32_t x = 0;
        int32_t y = 0;
        uint32_t w = 0; // 0 means "full width of target"
        uint32_t h = 0; // 0 means "full height of target"
        std::array<float, 4> rgba{ 1.0f, 1.0f, 1.0f, 1.0f };
        std::string name = "ClearRectLayer";
    };

    explicit ClearRectLayer(Config config);

    void record(VkCommandBuffer cmd, const std::vector<viz::ViewInfo>& views, const viz::RenderTarget& target) override;

    const Config& config() const noexcept
    {
        return config_;
    }

private:
    Config config_;
};

} // namespace viz::testing
