// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// NVENC H.264 encoder — single-frame in / single-packet out. Mirrors
// camera_streamer's NvStreamEncoderOp settings (P4 + ULTRA_LOW_LATENCY +
// CBR + bf=0 + IDR=fps*5 + nExtraOutputDelay=0). The output-delay=0 is
// the critical knob that's NOT exposed by PyNvVideoCodec 2.1 — the
// upstream wrapper holds back 3 frames before emitting, adding 100 ms
// at 30 fps. This native port closes that gap.

#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace camera_viz::codec
{

enum class PixelFormat
{
    // R,G,B,A byte order in memory. Matches numpy/cupy/torch RGBA tensors.
    kRGBA8,
    // B,G,R,A byte order in memory. Matches OpenCV BGRA frames.
    kBGRA8,
};

struct EncoderConfig
{
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t bitrate_bps = 15'000'000;
    uint32_t fps = 30;
    // GOP / IDR period. 0 → fps*5 (camera_streamer default — IDR every 5 s).
    uint32_t gop = 0;
    int gpu_id = 0;
    PixelFormat pixel_format = PixelFormat::kRGBA8;
};

class H264Encoder
{
public:
    explicit H264Encoder(const EncoderConfig& cfg);
    ~H264Encoder();

    H264Encoder(const H264Encoder&) = delete;
    H264Encoder& operator=(const H264Encoder&) = delete;
    H264Encoder(H264Encoder&&) = delete;
    H264Encoder& operator=(H264Encoder&&) = delete;

    // Encode one GPU-resident RGBA8 frame. ``rgba_device_ptr`` points to
    // the top-left of a HxWx4 buffer; ``row_pitch_bytes`` is the byte
    // stride between consecutive rows (== W*4 for tightly packed).
    //
    // Returns an Annex-B byte vector. Empty during NVENC warmup; this is
    // expected and not an error (the bitstream is just not flowing yet).
    // Throws std::runtime_error on NVENC failure — the caller is expected
    // to drop the encoder and reconstruct.
    std::vector<uint8_t> encode(uintptr_t rgba_device_ptr, std::size_t row_pitch_bytes);

    // Flush remaining packets from NVENC's internal queue. With
    // extraOutputDelay=0 this is normally empty, but bracket your stream
    // teardown with end_of_stream() anyway — defensive against any
    // future config that increases the queue depth.
    std::vector<uint8_t> end_of_stream();

    uint32_t width() const noexcept;
    uint32_t height() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace camera_viz::codec
