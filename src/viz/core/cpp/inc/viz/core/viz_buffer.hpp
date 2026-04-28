// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>

namespace core::viz
{

// Pixel formats supported by Televiz layers.
//
// kRGBA8 is the only color format used by built-in layers. kD32F is
// reserved for depth (used by ProjectionLayer once that layer ships).
enum class PixelFormat
{
    kRGBA8, // 4-channel uint8 color
    kD32F, // single-channel float32 depth
};

// Lightweight, non-owning reference to a 2D pixel buffer on GPU.
//
// VizBuffer carries no ownership semantics: it does not allocate or free
// memory. For Mode B submission (acquire/release), the layer owns the
// underlying interop buffer; VizBuffer is a view into it.
//
// In Python, VizBuffer exposes __cuda_array_interface__ so CuPy can wrap
// it zero-copy.
struct VizBuffer
{
    void* data = nullptr; // CUDA device pointer
    uint32_t width = 0;
    uint32_t height = 0;
    PixelFormat format = PixelFormat::kRGBA8;
    size_t pitch = 0; // Row pitch in bytes (0 = tightly packed)
};

// Returns the number of bytes per pixel for the given format.
constexpr uint32_t bytes_per_pixel(PixelFormat format) noexcept
{
    switch (format)
    {
    case PixelFormat::kRGBA8:
        return 4;
    case PixelFormat::kD32F:
        return 4;
    }
    return 0;
}

// Returns the effective row pitch in bytes for the buffer.
// If pitch is set (non-zero), returns it. Otherwise returns the
// tightly-packed pitch: width * bytes_per_pixel(format).
constexpr size_t effective_pitch(const VizBuffer& buf) noexcept
{
    return buf.pitch != 0 ? buf.pitch : static_cast<size_t>(buf.width) * bytes_per_pixel(buf.format);
}

} // namespace core::viz
