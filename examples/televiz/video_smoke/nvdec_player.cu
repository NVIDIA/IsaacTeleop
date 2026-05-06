// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "NvDecoder/NvDecoder.h"
#include "nvdec_player.hpp"

#include <cuda_runtime.h>
#include <fstream>
#include <ios>
#include <nppi_color_conversion.h>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace viz_smoke
{

namespace
{

void check_cu(CUresult r, const char* what)
{
    if (r != CUDA_SUCCESS)
    {
        const char* msg = nullptr;
        cuGetErrorString(r, &msg);
        throw std::runtime_error(std::string("NvdecPlayer: ") + what + " failed: " + (msg ? msg : "unknown"));
    }
}

void check_cuda(cudaError_t r, const char* what)
{
    if (r != cudaSuccess)
    {
        throw std::runtime_error(std::string("NvdecPlayer: ") + what + " failed: " + cudaGetErrorString(r));
    }
}

// Pack a tightly-packed 3-channel RGB image into a 4-channel RGBA
// image with alpha = 255. NPP doesn't ship a 4-channel NV12 -> RGBA
// variant for BT.709 limited range, so we use NPP for the
// colorspace conversion and this trivial kernel for the alpha pack.
__global__ void rgb_to_rgba_kernel(const uint8_t* __restrict__ rgb, uint8_t* __restrict__ rgba, int npixels)
{
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= npixels)
    {
        return;
    }
    const int s = i * 3;
    const int d = i * 4;
    rgba[d + 0] = rgb[s + 0];
    rgba[d + 1] = rgb[s + 1];
    rgba[d + 2] = rgb[s + 2];
    rgba[d + 3] = 255;
}

} // namespace

DecodedFrame::DecodedFrame(NvdecPlayer* p, uint8_t* d, uint32_t w, uint32_t h) noexcept
    : player(p), data(d), width(w), height(h)
{
}

DecodedFrame::~DecodedFrame()
{
    if (data != nullptr && player != nullptr)
    {
        player->release_buffer(data, width, height);
    }
}

DecodedFrame::DecodedFrame(DecodedFrame&& o) noexcept : player(o.player), data(o.data), width(o.width), height(o.height)
{
    o.player = nullptr;
    o.data = nullptr;
}

DecodedFrame& DecodedFrame::operator=(DecodedFrame&& o) noexcept
{
    if (this != &o)
    {
        if (data != nullptr && player != nullptr)
        {
            player->release_buffer(data, width, height);
        }
        player = o.player;
        data = o.data;
        width = o.width;
        height = o.height;
        o.player = nullptr;
        o.data = nullptr;
    }
    return *this;
}

NvdecPlayer::NvdecPlayer(int cuda_device_id, std::string file_path) : file_path_(std::move(file_path))
{
    check_cu(cuInit(0), "cuInit");
    check_cu(cuDeviceGet(&device_, cuda_device_id), "cuDeviceGet");
    check_cu(cuDevicePrimaryCtxRetain(&ctx_, device_), "cuDevicePrimaryCtxRetain");

    try
    {
        check_cuda(cudaSetDevice(cuda_device_id), "cudaSetDevice");
        check_cuda(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");

        cudaDeviceProp props{};
        cudaGetDeviceProperties(&props, cuda_device_id);
        npp_ctx_.hStream = stream_;
        npp_ctx_.nCudaDeviceId = cuda_device_id;
        npp_ctx_.nMultiProcessorCount = props.multiProcessorCount;
        npp_ctx_.nMaxThreadsPerMultiProcessor = props.maxThreadsPerMultiProcessor;
        npp_ctx_.nMaxThreadsPerBlock = props.maxThreadsPerBlock;
        npp_ctx_.nSharedMemPerBlock = props.sharedMemPerBlock;
        cudaDeviceGetAttribute(
            &npp_ctx_.nCudaDevAttrComputeCapabilityMajor, cudaDevAttrComputeCapabilityMajor, cuda_device_id);
        cudaDeviceGetAttribute(
            &npp_ctx_.nCudaDevAttrComputeCapabilityMinor, cudaDevAttrComputeCapabilityMinor, cuda_device_id);
        cudaStreamGetFlags(stream_, &npp_ctx_.nStreamFlags);

        decoder_ = std::make_unique<NvDecoder>(ctx_,
                                               /*bUseDeviceFrame=*/true, cudaVideoCodec_H264, /*bLowLatency=*/false);
    }
    catch (...)
    {
        if (stream_ != nullptr)
        {
            cudaStreamDestroy(stream_);
            stream_ = nullptr;
        }
        cuDevicePrimaryCtxRelease(device_);
        ctx_ = nullptr;
        throw;
    }

    // Spawn the worker AFTER all CUDA + decoder resources are valid,
    // so the worker can dive straight into reading the file.
    worker_ = std::thread(&NvdecPlayer::worker_loop, this, cuda_device_id);
}

NvdecPlayer::~NvdecPlayer()
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stop_ = true;
    }
    cv_.notify_all();
    if (worker_.joinable())
    {
        worker_.join();
    }

    // Release queued frames first — their dtor pushes back to
    // free_buffers_ via release_buffer, so the pool grows here.
    queue_.clear();
    for (uint8_t* p : free_buffers_)
    {
        cudaFree(p);
    }
    free_buffers_.clear();
    if (rgb_scratch_ != nullptr)
    {
        cudaFree(rgb_scratch_);
        rgb_scratch_ = nullptr;
    }
    decoder_.reset();
    if (stream_ != nullptr)
    {
        cudaStreamDestroy(stream_);
        stream_ = nullptr;
    }
    if (ctx_ != nullptr)
    {
        cuDevicePrimaryCtxRelease(device_);
        ctx_ = nullptr;
    }
}

void NvdecPlayer::release_buffer(uint8_t* p, uint32_t w, uint32_t h) noexcept
{
    if (p == nullptr)
    {
        return;
    }
    bool recycled = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (w == pool_w_ && h == pool_h_ && free_buffers_.size() < kPoolMax)
        {
            free_buffers_.push_back(p);
            recycled = true;
        }
    }
    if (!recycled)
    {
        cudaFree(p);
    }
    // Wake the worker — it may have been blocked on the queue cap.
    cv_.notify_all();
}

void NvdecPlayer::worker_loop(int cuda_device_id)
{
    // cudaSetDevice is per-thread; activate the same primary
    // context the constructor used so this thread's NPP/kernel/
    // memcpy work targets the right CUDA context.
    if (cudaSetDevice(cuda_device_id) != cudaSuccess)
    {
        return;
    }

    std::ifstream file(file_path_, std::ios::binary);
    if (!file)
    {
        return;
    }

    constexpr size_t kChunkBytes = 64 * 1024;
    std::vector<uint8_t> chunk(kChunkBytes);

    while (true)
    {
        // Backpressure: don't run too far ahead of the consumer.
        // Sleeps on cv until a frame is popped (release_buffer
        // notifies) or the destructor signals stop.
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [this]() { return stop_ || queue_.size() < kQueueMax; });
            if (stop_)
            {
                return;
            }
        }

        file.read(reinterpret_cast<char*>(chunk.data()), chunk.size());
        const auto got = static_cast<size_t>(file.gcount());
        if (!file)
        {
            file.clear();
            file.seekg(0);
        }
        if (got == 0)
        {
            continue;
        }

        int n_frames = 0;
        try
        {
            n_frames = decoder_->Decode(chunk.data(), static_cast<int>(got));
        }
        catch (const NVDECException&)
        {
            // Worker cannot throw across thread boundaries; just stop.
            return;
        }

        for (int i = 0; i < n_frames; ++i)
        {
            uint8_t* nv12 = decoder_->GetLockedFrame();
            if (nv12 == nullptr)
            {
                break;
            }

            const int w = decoder_->GetWidth();
            const int h = decoder_->GetHeight();
            const int pitch = decoder_->GetDeviceFramePitch();
            const int luma_size = decoder_->GetLumaPlaneSize();
            const size_t npixels = static_cast<size_t>(w) * h;

            // Pool keyed on (w, h). Drop on first resolution change.
            // The pool + rgb_scratch_ are protected by mutex_ since
            // release_buffer (consumer thread) also touches them.
            uint8_t* rgba = nullptr;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (pool_w_ != static_cast<uint32_t>(w) || pool_h_ != static_cast<uint32_t>(h))
                {
                    for (uint8_t* p : free_buffers_)
                    {
                        cudaFree(p);
                    }
                    free_buffers_.clear();
                    if (rgb_scratch_ != nullptr)
                    {
                        cudaFree(rgb_scratch_);
                        rgb_scratch_ = nullptr;
                    }
                    pool_w_ = static_cast<uint32_t>(w);
                    pool_h_ = static_cast<uint32_t>(h);
                }
                if (!free_buffers_.empty())
                {
                    rgba = free_buffers_.back();
                    free_buffers_.pop_back();
                }
            }

            if (rgb_scratch_ == nullptr)
            {
                if (cudaMalloc(reinterpret_cast<void**>(&rgb_scratch_), npixels * 3) != cudaSuccess)
                {
                    decoder_->UnlockFrame(&nv12);
                    return;
                }
            }
            if (rgba == nullptr)
            {
                if (cudaMalloc(reinterpret_cast<void**>(&rgba), npixels * 4) != cudaSuccess)
                {
                    decoder_->UnlockFrame(&nv12);
                    return;
                }
            }

            const Npp8u* nv12_planes[2] = { nv12, nv12 + luma_size };
            const NppiSize roi = { w, h };
            if (nppiNV12ToRGB_709CSC_8u_P2C3R_Ctx(nv12_planes, pitch, rgb_scratch_, w * 3, roi, npp_ctx_) != NPP_SUCCESS)
            {
                cudaFree(rgba);
                decoder_->UnlockFrame(&nv12);
                return;
            }

            const int block = 256;
            const int grid = (static_cast<int>(npixels) + block - 1) / block;
            rgb_to_rgba_kernel<<<grid, block, 0, stream_>>>(rgb_scratch_, rgba, static_cast<int>(npixels));
            const cudaError_t kerr = cudaGetLastError();
            decoder_->UnlockFrame(&nv12);
            if (kerr != cudaSuccess)
            {
                cudaFree(rgba);
                return;
            }

            auto frame = std::make_unique<DecodedFrame>(this, rgba, static_cast<uint32_t>(w), static_cast<uint32_t>(h));
            {
                std::lock_guard<std::mutex> lock(mutex_);
                queue_.push_back(std::move(frame));
            }
            cv_.notify_all();
        }
    }
}

double NvdecPlayer::frame_period_seconds() const noexcept
{
    if (!decoder_)
    {
        return 0.0;
    }
    const auto fmt = decoder_->GetVideoFormatInfo();
    if (fmt.frame_rate.numerator == 0 || fmt.frame_rate.denominator == 0)
    {
        return 0.0;
    }
    return static_cast<double>(fmt.frame_rate.denominator) / static_cast<double>(fmt.frame_rate.numerator);
}

std::unique_ptr<DecodedFrame> NvdecPlayer::try_pop()
{
    std::unique_ptr<DecodedFrame> front;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (queue_.empty())
        {
            return nullptr;
        }
        front = std::move(queue_.front());
        queue_.pop_front();
    }
    cv_.notify_all(); // worker may be waiting on queue cap
    return front;
}

} // namespace viz_smoke
