// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/session/tile_layout.hpp>

#include <algorithm>
#include <cmath>

namespace viz
{

namespace
{

// Aspect-fit `content_aspect` (w/h) inside an outer rect with sides
// `outer_w` x `outer_h`. Returns offset+extent inside the outer.
VkRect2D aspect_fit(float content_aspect, uint32_t outer_w, uint32_t outer_h)
{
    if (outer_w == 0 || outer_h == 0 || content_aspect <= 0.0f)
    {
        return VkRect2D{ { 0, 0 }, { 0, 0 } };
    }
    const float outer_aspect = static_cast<float>(outer_w) / static_cast<float>(outer_h);
    uint32_t fit_w = outer_w;
    uint32_t fit_h = outer_h;
    if (content_aspect > outer_aspect)
    {
        // content wider than outer → letterbox top/bottom
        fit_h = static_cast<uint32_t>(static_cast<float>(outer_w) / content_aspect);
    }
    else
    {
        // content taller than outer → letterbox left/right
        fit_w = static_cast<uint32_t>(static_cast<float>(outer_h) * content_aspect);
    }
    const int32_t off_x = static_cast<int32_t>((outer_w - fit_w) / 2);
    const int32_t off_y = static_cast<int32_t>((outer_h - fit_h) / 2);
    return VkRect2D{ { off_x, off_y }, { fit_w, fit_h } };
}

} // namespace

std::vector<TileSlot> tile_layout(const std::vector<float>& aspects, Resolution fb_size, uint32_t padding)
{
    const uint32_t n = static_cast<uint32_t>(aspects.size());
    if (n == 0 || fb_size.width == 0 || fb_size.height == 0)
    {
        return {};
    }

    // Row-major grid. cols = ceil(sqrt(n)), rows = ceil(n / cols).
    const uint32_t cols = static_cast<uint32_t>(std::ceil(std::sqrt(static_cast<double>(n))));
    const uint32_t rows = (n + cols - 1) / cols;

    // Equal-slice per tile (integer division — last column/row absorbs
    // the remainder so the grid covers the whole framebuffer).
    const uint32_t base_tile_w = fb_size.width / cols;
    const uint32_t base_tile_h = fb_size.height / rows;

    std::vector<TileSlot> slots;
    slots.reserve(n);
    for (uint32_t i = 0; i < n; ++i)
    {
        const uint32_t row = i / cols;
        const uint32_t col = i % cols;

        const uint32_t tile_x = col * base_tile_w;
        const uint32_t tile_y = row * base_tile_h;
        const uint32_t tile_w = (col == cols - 1) ? (fb_size.width - tile_x) : base_tile_w;
        const uint32_t tile_h = (row == rows - 1) ? (fb_size.height - tile_y) : base_tile_h;

        // Apply padding by shrinking the outer tile symmetrically. If
        // padding swallows the tile, clamp to a 1x1 to keep downstream
        // viewport binds happy.
        const uint32_t pad_w = std::min(padding, tile_w / 2);
        const uint32_t pad_h = std::min(padding, tile_h / 2);
        const uint32_t outer_w = std::max<uint32_t>(1, tile_w - 2 * pad_w);
        const uint32_t outer_h = std::max<uint32_t>(1, tile_h - 2 * pad_h);
        const int32_t outer_x = static_cast<int32_t>(tile_x + pad_w);
        const int32_t outer_y = static_cast<int32_t>(tile_y + pad_h);

        TileSlot slot{};
        slot.outer = VkRect2D{ { outer_x, outer_y }, { outer_w, outer_h } };

        // Aspect-fit content rect inside outer, then translate.
        const VkRect2D fit = aspect_fit(aspects[i], outer_w, outer_h);
        slot.content = VkRect2D{ { outer_x + fit.offset.x, outer_y + fit.offset.y }, fit.extent };

        slots.push_back(slot);
    }
    return slots;
}

} // namespace viz
