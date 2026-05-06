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

DecodedFrame::DecodedFrame(uint8_t* d, uint32_t w, uint32_t h) noexcept : data(d), width(w), height(h)
{
}

DecodedFrame::~DecodedFrame()
{
    if (data != nullptr)
    {
        cudaFree(data);
    }
}

DecodedFrame::DecodedFrame(DecodedFrame&& o) noexcept : data(o.data), width(o.width), height(o.height)
{
    o.data = nullptr;
}

DecodedFrame& DecodedFrame::operator=(DecodedFrame&& o) noexcept
{
    if (this != &o)
    {
        if (data != nullptr)
        {
            cudaFree(data);
        }
        data = o.data;
        width = o.width;
        height = o.height;
        o.data = nullptr;
    }
    return *this;
}

NvdecPlayer::NvdecPlayer()
{
    check_cu(cuInit(0), "cuInit");
    check_cu(cuDeviceGet(&device_, 0), "cuDeviceGet");
    check_cu(cuDevicePrimaryCtxRetain(&ctx_, device_), "cuDevicePrimaryCtxRetain");

    CtxScope scope(ctx_);
    try
    {
        // Display-order output (default). bLowLatency / bForceZeroLatency
        // off so B-frames are buffered and emitted in display order.
        decoder_ = std::make_unique<NvDecoder>(ctx_,
                                               /*bUseDeviceFrame=*/true, cudaVideoCodec_H264, /*bLowLatency=*/false);
    }
    catch (...)
    {
        cuDevicePrimaryCtxRelease(device_);
        ctx_ = nullptr;
        throw;
    }
}

NvdecPlayer::~NvdecPlayer()
{
    queue_.clear(); // cudaFree under valid context
    decoder_.reset();
    if (ctx_ != nullptr)
    {
        cuDevicePrimaryCtxRelease(device_);
        ctx_ = nullptr;
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

        // Allocate intermediate RGB + final RGBA. The intermediate is
        // freed at end of scope (cudaFreeAsync would need a stream).
        uint8_t* rgb = nullptr;
        uint8_t* rgba = nullptr;
        check_cuda(cudaMalloc(reinterpret_cast<void**>(&rgb), npixels * 3), "cudaMalloc(rgb)");
        const cudaError_t alloc_rgba = cudaMalloc(reinterpret_cast<void**>(&rgba), npixels * 4);
        if (alloc_rgba != cudaSuccess)
        {
            cudaFree(rgb);
            decoder_->UnlockFrame(&nv12);
            throw std::runtime_error(std::string("NvdecPlayer: cudaMalloc(rgba) failed: ") +
                                     cudaGetErrorString(alloc_rgba));
        }

        const Npp8u* nv12_planes[2] = { nv12, nv12 + luma_size };
        const NppiSize roi = { w, h };
        check_npp(nppiNV12ToRGB_709CSC_8u_P2C3R(nv12_planes, pitch, rgb, w * 3, roi), "nppiNV12ToRGB_709CSC_8u_P2C3R");

        const int block = 256;
        const int grid = (static_cast<int>(npixels) + block - 1) / block;
        rgb_to_rgba_kernel<<<grid, block>>>(rgb, rgba, static_cast<int>(npixels));
        const cudaError_t kerr = cudaGetLastError();
        cudaFree(rgb);
        decoder_->UnlockFrame(&nv12);
        if (kerr != cudaSuccess)
        {
            cudaFree(rgba);
            throw std::runtime_error(std::string("NvdecPlayer: rgb_to_rgba kernel failed: ") + cudaGetErrorString(kerr));
        }

        queue_.push_back(std::make_unique<DecodedFrame>(rgba, static_cast<uint32_t>(w), static_cast<uint32_t>(h)));
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
