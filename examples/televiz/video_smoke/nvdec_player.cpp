// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "nvdec_player.hpp"

#include "NvDecoder/NvDecoder.h"
#include "nv12_to_rgba.cuh"

#include <stdexcept>
#include <string>
#include <utility>

namespace viz_smoke
{

namespace
{

void cu_check(CUresult r, const char* what)
{
    if (r != CUDA_SUCCESS)
    {
        const char* msg = nullptr;
        cuGetErrorString(r, &msg);
        throw std::runtime_error(std::string("NvdecPlayer: ") + what + " failed: " + (msg ? msg : "unknown"));
    }
}

void cuda_check(cudaError_t r, const char* what)
{
    if (r != cudaSuccess)
    {
        throw std::runtime_error(std::string("NvdecPlayer: ") + what + " failed: " + cudaGetErrorString(r));
    }
}

} // namespace

OwnedRgba::~OwnedRgba()
{
    if (data != nullptr)
    {
        cudaFree(data);
        data = nullptr;
    }
}

OwnedRgba& OwnedRgba::operator=(OwnedRgba&& o) noexcept
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
        o.width = 0;
        o.height = 0;
    }
    return *this;
}

NvdecPlayer::NvdecPlayer()
{
    cu_check(cuInit(0), "cuInit");
    cu_check(cuDeviceGet(&cu_device_, 0), "cuDeviceGet");
    cu_check(cuDevicePrimaryCtxRetain(&cu_context_, cu_device_), "cuDevicePrimaryCtxRetain");

    cu_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent");
    try
    {
        // bLowLatency=false / bForceZeroLatency=false: we want display
        // order, not decode order. With B-frames the two differ; the
        // zero-latency path returns frames as-decoded (I, P, B, B, ...)
        // which would render as visible jitter. The cost is the
        // decoder buffering up to a B-frame group internally before
        // releasing — fine for file playback.
        decoder_ = std::make_unique<NvDecoder>(cu_context_,
                                               /*bUseDeviceFrame=*/true, cudaVideoCodec_H264, /*bLowLatency=*/false,
                                               /*bDeviceFramePitched=*/false,
                                               /*pCropRect=*/nullptr,
                                               /*pResizeDim=*/nullptr,
                                               /*bExtractSEIMessage=*/false,
                                               /*nMaxWidth=*/0,
                                               /*nMaxHeight=*/0,
                                               /*nClockRate=*/1000,
                                               /*bForceZeroLatency=*/false);
    }
    catch (...)
    {
        cuCtxPopCurrent(nullptr);
        if (cu_context_ != nullptr)
        {
            cuDevicePrimaryCtxRelease(cu_device_);
            cu_context_ = nullptr;
        }
        throw;
    }
    cu_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
}

NvdecPlayer::~NvdecPlayer()
{
    // Release queued frames before the CUDA context goes away — their
    // cudaFree in ~OwnedRgba needs a valid context.
    ready_.clear();
    decoder_.reset();
    if (cu_context_ != nullptr)
    {
        cuDevicePrimaryCtxRelease(cu_device_);
        cu_context_ = nullptr;
    }
}

bool NvdecPlayer::feed(const uint8_t* data, size_t size)
{
    if (data == nullptr || size == 0)
    {
        return !ready_.empty();
    }

    cu_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent(decode)");
    int n_frames = 0;
    try
    {
        n_frames = decoder_->Decode(data, static_cast<int>(size));
    }
    catch (const NVDECException& e)
    {
        cuCtxPopCurrent(nullptr);
        throw std::runtime_error(std::string("NvdecPlayer: NvDecoder::Decode failed: ") + e.what());
    }

    // Drain every frame the decoder released; if we leave any locked,
    // the next Decode() may overwrite them and we visibly drop frames.
    for (int i = 0; i < n_frames; ++i)
    {
        uint8_t* nv12 = decoder_->GetLockedFrame();
        if (nv12 == nullptr)
        {
            break;
        }

        // Read the H.264 VUI's video_full_range_flag once. H.264
        // defaults to limited range when the flag is absent (Annex E),
        // so unset → BT.709 limited; set → BT.601 full.
        if (!color_range_detected_)
        {
            const auto fmt = decoder_->GetVideoFormatInfo();
            use_full_range_ = fmt.video_signal_description.video_full_range_flag != 0;
            color_range_detected_ = true;
        }

        const int w = decoder_->GetWidth();
        const int h = decoder_->GetHeight();
        const int pitch = decoder_->GetDeviceFramePitch();
        const int luma_size = decoder_->GetLumaPlaneSize();

        uint8_t* rgba = nullptr;
        const size_t bytes = static_cast<size_t>(w) * h * 4;
        const cudaError_t alloc_err = cudaMalloc(reinterpret_cast<void**>(&rgba), bytes);
        if (alloc_err != cudaSuccess)
        {
            decoder_->UnlockFrame(&nv12);
            cuCtxPopCurrent(nullptr);
            throw std::runtime_error(std::string("NvdecPlayer: cudaMalloc(rgba) failed: ") +
                                     cudaGetErrorString(alloc_err));
        }

        if (use_full_range_)
        {
            nv12_to_rgba_fullrange_bt601(nv12, nv12 + luma_size, pitch, rgba, w * 4, w, h, /*stream=*/0);
        }
        else
        {
            nv12_to_rgba_limited_bt709(nv12, nv12 + luma_size, pitch, rgba, w * 4, w, h, /*stream=*/0);
        }
        const cudaError_t kernel_err = cudaGetLastError();
        decoder_->UnlockFrame(&nv12);
        if (kernel_err != cudaSuccess)
        {
            cudaFree(rgba);
            cuCtxPopCurrent(nullptr);
            throw std::runtime_error(std::string("NvdecPlayer: NV12->RGBA kernel failed: ") +
                                     cudaGetErrorString(kernel_err));
        }

        ready_.push_back(std::make_unique<OwnedRgba>(rgba, static_cast<uint32_t>(w), static_cast<uint32_t>(h)));
    }

    cu_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent(post-drain)");
    return !ready_.empty();
}

std::unique_ptr<OwnedRgba> NvdecPlayer::try_pop()
{
    if (ready_.empty())
    {
        return nullptr;
    }
    auto front = std::move(ready_.front());
    ready_.pop_front();
    return front;
}

} // namespace viz_smoke
