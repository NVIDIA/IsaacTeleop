// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <cuda.h>
#include <cuda_runtime.h>
#include <deque>
#include <memory>

class NvDecoder;

namespace viz_smoke
{

// RAII for a cudaMalloc'd RGBA8 buffer.
struct OwnedRgba
{
    uint8_t* data = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;

    OwnedRgba() = default;
    OwnedRgba(uint8_t* p, uint32_t w, uint32_t h) noexcept : data(p), width(w), height(h)
    {
    }
    ~OwnedRgba();
    OwnedRgba(const OwnedRgba&) = delete;
    OwnedRgba& operator=(const OwnedRgba&) = delete;
    OwnedRgba(OwnedRgba&& o) noexcept : data(o.data), width(o.width), height(o.height)
    {
        o.data = nullptr;
        o.width = 0;
        o.height = 0;
    }
    OwnedRgba& operator=(OwnedRgba&& o) noexcept;
};

// Decodes an H.264 Annex B stream into a queue of device-resident
// RGBA8 frames in display order. NvDecoder's Decode() returns N
// frames at a time (especially after a B-frame group); we drain all
// of them per call and queue them. Callers pop one frame per render
// iteration via try_pop().
class NvdecPlayer
{
public:
    NvdecPlayer();
    ~NvdecPlayer();

    NvdecPlayer(const NvdecPlayer&) = delete;
    NvdecPlayer& operator=(const NvdecPlayer&) = delete;

    // Push one Annex B NAL unit (with start code) into the decoder.
    // Drains any newly-available frames into the internal queue.
    // Returns true if at least one frame is now queued (or already
    // was). NAL units that only update parameter sets (SPS/PPS) or
    // contain partial-picture data legitimately produce no frames —
    // keep feeding.
    bool feed(const uint8_t* data, size_t size);

    // Pop the next display-order frame. Returns nullptr if the queue
    // is empty. Caller takes ownership and must keep the OwnedRgba
    // alive for at least one full render() cycle after submit() —
    // QuadLayer::submit issues an async memcpy from the buffer that
    // only completes during the next render's GPU wait.
    std::unique_ptr<OwnedRgba> try_pop();

    size_t queued_frame_count() const noexcept
    {
        return ready_.size();
    }

private:
    CUdevice cu_device_ = 0;
    CUcontext cu_context_ = nullptr;
    std::unique_ptr<NvDecoder> decoder_;

    std::deque<std::unique_ptr<OwnedRgba>> ready_;

    // VUI-driven choice of NV12->RGBA kernel. Read once after the
    // first decoded frame; the bitstream's color signaling shouldn't
    // change mid-stream in any sane file. Default = limited BT.709
    // (the H.264 default per the spec) until we know otherwise.
    bool color_range_detected_ = false;
    bool use_full_range_ = false;
};

} // namespace viz_smoke
