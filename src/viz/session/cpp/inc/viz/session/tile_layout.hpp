// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <vector>

namespace viz
{

// Per-layer tile + content rectangles produced by tile_layout().
//
// outer:   the layer's tile, an equal slice of the framebuffer in
//          row-major order. The compositor binds this as the scissor
//          before calling the layer's record(), so even if the layer
//          over-draws it cannot leak into a neighbor's tile.
// content: the aspect-fit content rect inside `outer`, centered. The
//          layer binds this as its viewport (one entry per ViewInfo)
//          so its texture renders at correct aspect — the unused
//          margins between content and outer keep the framebuffer's
//          clear color (free letterbox).
struct TileSlot
{
    VkRect2D outer{};
    VkRect2D content{};
};

// Compute a row-major aspect-preserving tile grid for N visible
// layers in a `fb_size` framebuffer.
//
// `aspects`: width/height ratio per visible layer, in insertion order.
//            aspects.size() determines the grid (cols = ceil(sqrt(N)),
//            rows = ceil(N / cols)).
// `padding`: pixels of inter-tile gap (for visual breathing room).
//            Subtracted symmetrically from each tile before computing
//            the content rect.
//
// Returns aspects.size() entries. Empty input -> empty output.
std::vector<TileSlot> tile_layout(const std::vector<float>& aspects, Resolution fb_size, uint32_t padding = 0);

} // namespace viz
