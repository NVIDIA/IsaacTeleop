// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "NvDecoder/NvDecoder.h"
#include "nvdec_player.hpp"

#include <cuda_runtime.h>
#include <nppi_color_conversion.h>
#include <stdexcept>
#include <string>

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

void check_npp(NppStatus s, const char* what)
{
    if (s != NPP_SUCCESS)
    {
        throw std::runtime_error(std::string("NvdecPlayer: ") + what + " failed: NppStatus=" + std::to_string(s));
    }
}

// RAII for cuCtxPushCurrent / cuCtxPopCurrent. Methods that touch
// the decoder or NPP wrap their body in this so we run on the
// right primary context.
struct CtxScope
{
    explicit CtxScope(CUcontext c)
    {
        check_cu(cuCtxPushCurrent(c), "cuCtxPushCurrent");
    }
    ~CtxScope()
    {
        cuCtxPopCurrent(nullptr);
    }
};

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

NvdecPlayer::NvdecPlayer(int cuda_device_id)
{
    check_cu(cuInit(0), "cuInit");
    check_cu(cuDeviceGet(&device_, cuda_device_id), "cuDeviceGet");
    check_cu(cuDevicePrimaryCtxRetain(&ctx_, device_), "cuDevicePrimaryCtxRetain");

    try
    {
        // Activate the primary context via the runtime API so the
        // stream we create is in the same context the renderer's
        // QuadLayer::submit will use (it calls cudaSetDevice + the
        // imported external semaphore was registered under that
        // same primary context). Mixing manual cuCtxPushCurrent
        // for stream creation with runtime API for signal causes
        // cudaSignalExternalSemaphoresAsync to fail with
        // "invalid argument".
        check_cuda(cudaSetDevice(cuda_device_id), "cudaSetDevice");

        // Per-player non-blocking stream so multiple players don't
        // serialize their NPP / kernel / upload work on the default
        // stream. cudaStreamNonBlocking decouples from stream 0.
        check_cuda(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");

        // NPP stream context — populated once at construction so
        // feed() doesn't pay cudaGetDeviceProperties per frame.
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

        // NvDecoder pushes its own ctx internally for its driver
        // API calls; bLowLatency / bForceZeroLatency off so B-frames
        // are buffered and emitted in display order.
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
}

NvdecPlayer::~NvdecPlayer()
{
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
    // Recycle if the buffer matches the current pool dimensions and
    // we have room. Otherwise fall through to cudaFree to keep the
    // pool bounded (e.g. after a resolution change).
    if (w == pool_w_ && h == pool_h_ && free_buffers_.size() < kPoolMax)
    {
        free_buffers_.push_back(p);
    }
    else
    {
        cudaFree(p);
    }
}

void NvdecPlayer::feed(const uint8_t* data, size_t size)
{
    if (data == nullptr || size == 0)
    {
        return;
    }

    CtxScope scope(ctx_);

    int n_frames = 0;
    try
    {
        n_frames = decoder_->Decode(data, static_cast<int>(size));
    }
    catch (const NVDECException& e)
    {
        throw std::runtime_error(std::string("NvdecPlayer: NvDecoder::Decode failed: ") + e.what());
    }

    // Drain everything; un-fetched frames are lost when the next
    // Decode() recycles the decode surface.
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

        // Pool is keyed on (w, h). Drop on first resolution change.
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

        // Lazily allocate the RGB scratch buffer the first time we
        // see this resolution. Reused for every drained frame —
        // feed() is serialized per player, so one buffer suffices
        // and we avoid cudaMalloc/cudaFree per frame.
        if (rgb_scratch_ == nullptr)
        {
            check_cuda(cudaMalloc(reinterpret_cast<void**>(&rgb_scratch_), npixels * 3), "cudaMalloc(rgb_scratch)");
        }

        // Take a recycled RGBA buffer if available; cudaMalloc only
        // when the pool is empty.
        uint8_t* rgba = nullptr;
        if (!free_buffers_.empty())
        {
            rgba = free_buffers_.back();
            free_buffers_.pop_back();
        }
        else
        {
            check_cuda(cudaMalloc(reinterpret_cast<void**>(&rgba), npixels * 4), "cudaMalloc(rgba)");
        }

        const Npp8u* nv12_planes[2] = { nv12, nv12 + luma_size };
        const NppiSize roi = { w, h };
        check_npp(nppiNV12ToRGB_709CSC_8u_P2C3R_Ctx(nv12_planes, pitch, rgb_scratch_, w * 3, roi, npp_ctx_),
                  "nppiNV12ToRGB_709CSC_8u_P2C3R_Ctx");

        const int block = 256;
        const int grid = (static_cast<int>(npixels) + block - 1) / block;
        rgb_to_rgba_kernel<<<grid, block, 0, stream_>>>(rgb_scratch_, rgba, static_cast<int>(npixels));
        const cudaError_t kerr = cudaGetLastError();
        decoder_->UnlockFrame(&nv12);
        if (kerr != cudaSuccess)
        {
            cudaFree(rgba);
            throw std::runtime_error(std::string("NvdecPlayer: rgb_to_rgba kernel failed: ") + cudaGetErrorString(kerr));
        }

        queue_.push_back(std::make_unique<DecodedFrame>(this, rgba, static_cast<uint32_t>(w), static_cast<uint32_t>(h)));
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
    if (queue_.empty())
    {
        return nullptr;
    }
    auto front = std::move(queue_.front());
    queue_.pop_front();
    return front;
}

} // namespace viz_smoke
