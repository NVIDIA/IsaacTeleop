// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <cuda.h>
#include <deque>
#include <memory>
#include <nppdefs.h>
#include <vector>

class NvDecoder;

namespace viz_smoke
{

class NvdecPlayer;

// One decoded RGBA8 frame on GPU memory. The buffer is owned by the
// originating NvdecPlayer's pool; ~DecodedFrame returns it for reuse
// (or cudaFrees it if the pool is full or the size mismatches).
struct DecodedFrame
{
    NvdecPlayer* player = nullptr; // non-owning back-pointer for recycle
    uint8_t* data = nullptr;
    uint32_t width = 0;
    uint32_t height = 0;

    DecodedFrame() = default;
    DecodedFrame(NvdecPlayer* p, uint8_t* d, uint32_t w, uint32_t h) noexcept;
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
    // cuda_device_id MUST match the CUDA device that VkContext
    // matched to Vulkan via UUID — VkContext::cuda_device_id().
    // Mismatch makes cudaSignalExternalSemaphoresAsync fail with
    // "invalid argument" on the QuadLayer's external semaphore.
    explicit NvdecPlayer(int cuda_device_id);
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

    // Per-player CUDA stream. Pass this to QuadLayer::submit so the
    // upload memcpy serializes with our NPP + kernel work but runs
    // in parallel with other players' streams.
    cudaStream_t stream() const noexcept
    {
        return stream_;
    }

    // Called by ~DecodedFrame to return its buffer to the pool.
    // Public because the back-pointer in DecodedFrame needs it; not
    // intended for direct caller use.
    void release_buffer(uint8_t* p, uint32_t w, uint32_t h) noexcept;

private:
    // Cap to bound memory if a B-frame group is larger than typical.
    // 8 buffers at 1080p RGBA8 = 64 MB per stream, ample for any
    // realistic GOP.
    static constexpr size_t kPoolMax = 8;

    CUdevice device_ = 0;
    CUcontext ctx_ = nullptr;
    cudaStream_t stream_ = nullptr;
    NppStreamContext npp_ctx_{};
    std::unique_ptr<NvDecoder> decoder_;

    std::deque<std::unique_ptr<DecodedFrame>> queue_;

    // Recycled buffers, all sized to (pool_w_ x pool_h_ x 4) bytes.
    // Resolution change (rare in a single-stream playback) drops the
    // pool and starts over.
    std::vector<uint8_t*> free_buffers_;
    uint32_t pool_w_ = 0;
    uint32_t pool_h_ = 0;

    // RGB intermediate (NPP output before alpha pack). Allocated
    // once per stream, reused by every feed() call. feed() is
    // serialized per player, so a single buffer is sufficient.
    uint8_t* rgb_scratch_ = nullptr;
};

} // namespace viz_smoke
