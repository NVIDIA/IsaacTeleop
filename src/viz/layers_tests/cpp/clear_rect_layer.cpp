// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/layers/testing/clear_rect_layer.hpp>

namespace viz::testing
{

ClearRectLayer::ClearRectLayer(Config config) : LayerBase(config.name), config_(std::move(config))
{
}

void ClearRectLayer::record(VkCommandBuffer cmd,
                            const std::vector<viz::ViewInfo>& /*views*/,
                            const viz::RenderTarget& target)
{
    VkClearAttachment attachment{};
    attachment.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    attachment.colorAttachment = 0;
    attachment.clearValue.color = { { config_.rgba[0], config_.rgba[1], config_.rgba[2], config_.rgba[3] } };

    const auto target_res = target.resolution();
    const uint32_t w = (config_.w == 0) ? target_res.width : config_.w;
    const uint32_t h = (config_.h == 0) ? target_res.height : config_.h;

    VkClearRect rect{};
    rect.rect.offset = { config_.x, config_.y };
    rect.rect.extent = { w, h };
    rect.baseArrayLayer = 0;
    rect.layerCount = 1;

    vkCmdClearAttachments(cmd, 1, &attachment, 1, &rect);
}

} // namespace viz::testing
