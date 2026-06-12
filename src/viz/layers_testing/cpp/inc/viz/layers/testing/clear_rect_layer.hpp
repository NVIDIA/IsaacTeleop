// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/session/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <vector>

namespace viz::testing
{

// Test layer: clears a rect to RGBA via vkCmdClearAttachments. Used to
// exercise the compositor's record path without shaders / pipelines.
// Origin top-left; w=h=0 means full target.
class ClearRectLayer final : public LayerBase
{
public:
    struct Config
    {
        int32_t x = 0;
        int32_t y = 0;
        uint32_t w = 0; // 0 = full target width
        uint32_t h = 0; // 0 = full target height
        std::array<float, 4> rgba{ 1.0f, 1.0f, 1.0f, 1.0f };
        std::string name = "ClearRectLayer";
    };

    explicit ClearRectLayer(Config config);

    void record(VkCommandBuffer cmd,
                const std::vector<viz::ViewInfo>& views,
                const viz::RenderTarget& target,
                uint32_t in_flight_slot) override;

    const Config& config() const noexcept
    {
        return config_;
    }

private:
    Config config_;
};

} // namespace viz::testing
