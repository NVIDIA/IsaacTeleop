// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>

#include <cstddef>
#include <cstdint>
#include <vector>

namespace viz
{

// Owning host-side 2D pixel buffer. Returned by readback paths that
// bring a composited frame back to CPU memory for tests, debug tooling,
// or non-CUDA consumers. Exposes a VizBuffer view (with
// MemorySpace::kHost) so the same helpers that operate on GPU
// VizBuffers (e.g. future save_to_png, image-diff) work on host data
// without parallel APIs.
//
// Layout: tightly packed (row_pitch = width * bytes_per_pixel(format)).
// Pixel rows are top-to-bottom. Channel order matches `format`.
class HostImage
{
public:
    HostImage() = default;
    HostImage(Resolution resolution, PixelFormat format)
        : resolution_(resolution),
          format_(format),
          storage_(static_cast<size_t>(resolution.width) * resolution.height * bytes_per_pixel(format))
    {
    }

    // Non-owning view into the storage as a VizBuffer (space = kHost).
    // Valid as long as this HostImage is alive and not moved-from.
    VizBuffer view() noexcept
    {
        return make_view(storage_.data());
    }

    // Const view; .data points at non-const memory but the caller should
    // treat it as read-only — Vulkan/CUDA interfaces want non-const ptrs.
    VizBuffer view() const noexcept
    {
        return make_view(const_cast<uint8_t*>(storage_.data()));
    }

    Resolution resolution() const noexcept
    {
        return resolution_;
    }
    PixelFormat format() const noexcept
    {
        return format_;
    }

    uint8_t* data() noexcept
    {
        return storage_.data();
    }
    const uint8_t* data() const noexcept
    {
        return storage_.data();
    }
    size_t size_bytes() const noexcept
    {
        return storage_.size();
    }

private:
    VizBuffer make_view(uint8_t* ptr) const noexcept
    {
        VizBuffer b;
        b.data = ptr;
        b.width = resolution_.width;
        b.height = resolution_.height;
        b.format = format_;
        b.pitch = static_cast<size_t>(resolution_.width) * bytes_per_pixel(format_);
        b.space = MemorySpace::kHost;
        return b;
    }

    Resolution resolution_{};
    PixelFormat format_ = PixelFormat::kRGBA8;
    std::vector<uint8_t> storage_;
};

} // namespace viz
