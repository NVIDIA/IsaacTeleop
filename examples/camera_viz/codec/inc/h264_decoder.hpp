// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// NVDEC H.264 decoder + NV12→RGBA8 color conversion. Mirrors
// camera_streamer's NvStreamDecoderOp (bLowLatency=true,
// bForceZeroLatency=true → no reorder buffer, decode-order output).
// NV12→RGBA8 is one CUDA kernel launch, supporting both BT.709
// limited-range (H.264 default) and BT.601 full-range (OAK-D VPU).

#pragma once

#include <cstdint>
#include <memory>

namespace camera_viz::codec
{

struct DecoderConfig
{
    uint32_t width = 0;
    uint32_t height = 0;
    // BT.601 full-range (ITU-T T.871). True for OAK-D VPU streams,
    // false for standard H.264 (BT.709 limited 16-235).
    bool full_range = false;
    int gpu_id = 0;
};

class H264Decoder
{
public:
    explicit H264Decoder(const DecoderConfig& cfg);
    ~H264Decoder();

    H264Decoder(const H264Decoder&) = delete;
    H264Decoder& operator=(const H264Decoder&) = delete;
    H264Decoder(H264Decoder&&) = delete;
    H264Decoder& operator=(H264Decoder&&) = delete;

    // Feed one Annex-B access unit. Returns true iff a frame was produced
    // and converted into the caller's RGBA8 buffer. ``rgba_out_device_ptr``
    // points to the top-left of a HxWx4 GPU buffer; ``row_pitch_bytes`` is
    // the row byte stride (== W*4 for tightly packed).
    //
    // The conversion runs on an internal CUDA stream and the call returns
    // only after the kernel completes — the buffer is safe for the
    // consumer to read on any stream as soon as decode() returns.
    bool decode(const uint8_t* packet, std::size_t packet_size,
                uintptr_t rgba_out_device_ptr, std::size_t row_pitch_bytes);

    // Tear down the NVDEC state. Used on stream-timeout / disconnect so
    // the next packet sees a fresh DPB (stale references after a long
    // silence produce green or scrambled frames once the stream resumes).
    void reset();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace camera_viz::codec
