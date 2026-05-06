// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <cuda.h>
#include <deque>
#include <memory>

class NvDecoder;

namespace viz_smoke
{

// One decoded RGBA8 frame on GPU memory, owns its own allocation.
struct DecodedFrame
{
    uint8_t* data = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;

    DecodedFrame() = default;
    DecodedFrame(uint8_t* d, uint32_t w, uint32_t h) noexcept;
    ~DecodedFrame();
    DecodedFrame(const DecodedFrame&) = delete;
    DecodedFrame& operator=(const DecodedFrame&) = delete;
    DecodedFrame(DecodedFrame&& o) noexcept;
    DecodedFrame& operator=(DecodedFrame&& o) noexcept;
};

// H.264 bitstream chunk -> queue of RGBA8 frames in display order.
// Uses NVDEC for decode (via the NVIDIA Video Codec SDK's NvDecoder
// wrapper) and NPP for NV12 -> RGB (BT.709 limited-range) plus a
// small CUDA kernel for the RGB -> RGBA alpha pack.
class NvdecPlayer
{
public:
    NvdecPlayer();
    ~NvdecPlayer();

    NvdecPlayer(const NvdecPlayer&) = delete;
    NvdecPlayer& operator=(const NvdecPlayer&) = delete;

    // Push a chunk of H.264 bytes (Annex B or MP4-mode — NvDecoder's
    // parser handles either). Drains all decoded frames into the queue.
    void feed(const uint8_t* data, size_t size);

    // Pop the next display-order frame, or nullptr if the queue is empty.
    std::unique_ptr<DecodedFrame> try_pop();

    size_t queued_frame_count() const noexcept
    {
        return queue_.size();
    }

    // Source frame period in seconds, read from the H.264 VUI on the
    // first decoded frame. Returns 0 if unspecified (variable frame
    // rate, or the encoder didn't emit timing_info) — caller should
    // fall back to a default cadence in that case.
    double frame_period_seconds() const noexcept;

private:
    CUdevice device_ = 0;
    CUcontext ctx_ = nullptr;
    std::unique_ptr<NvDecoder> decoder_;

    std::deque<std::unique_ptr<DecodedFrame>> queue_;
};

} // namespace viz_smoke
