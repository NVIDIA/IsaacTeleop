// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <cuda.h>
#include <cuda_runtime.h>
#include <memory>

class NvDecoder;

namespace viz_smoke
{

// Decodes an H.264 Annex B stream into device-resident RGBA8 frames.
// Holds its own primary CUDA context + a single RGBA8 output buffer
// that's reallocated when the stream's resolution changes. The
// caller copies out via cudaMemcpyAsync before pushing more bytes —
// the buffer is reused for the next frame.
class NvdecPlayer
{
public:
    struct DecodedFrame
    {
        const uint8_t* data; // device pointer, RGBA8 packed
        uint32_t width;
        uint32_t height;
        size_t pitch; // bytes per row, equal to width * 4
    };

    NvdecPlayer();
    ~NvdecPlayer();

    NvdecPlayer(const NvdecPlayer&) = delete;
    NvdecPlayer& operator=(const NvdecPlayer&) = delete;

    // Push one Annex B NAL unit (with start code) into the decoder.
    // Returns true if a fresh frame is now available via current_frame().
    // Returns false if the decoder needs more data (typical for SPS/PPS
    // before the first IDR) — keep feeding.
    bool feed(const uint8_t* data, size_t size);

    // Valid only directly after feed() returned true. Pointer remains
    // valid until the next feed() call.
    DecodedFrame current_frame() const noexcept
    {
        return current_;
    }

private:
    void ensure_rgba_buffer(uint32_t width, uint32_t height);

    CUdevice cu_device_ = 0;
    CUcontext cu_context_ = nullptr;
    std::unique_ptr<NvDecoder> decoder_;

    uint8_t* rgba_buffer_ = nullptr;
    uint32_t rgba_width_ = 0;
    uint32_t rgba_height_ = 0;

    DecodedFrame current_{};
};

} // namespace viz_smoke
