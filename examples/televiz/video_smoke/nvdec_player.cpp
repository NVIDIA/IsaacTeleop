// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "nvdec_player.hpp"

#include "NvDecoder/NvDecoder.h"
#include "nv12_to_rgba.cuh"

#include <stdexcept>
#include <string>

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

NvdecPlayer::NvdecPlayer()
{
    cu_check(cuInit(0), "cuInit");
    cu_check(cuDeviceGet(&cu_device_, 0), "cuDeviceGet");
    cu_check(cuDevicePrimaryCtxRetain(&cu_context_, cu_device_), "cuDevicePrimaryCtxRetain");

    cu_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent");
    try
    {
        decoder_ = std::make_unique<NvDecoder>(cu_context_,
                                               /*bUseDeviceFrame=*/true, cudaVideoCodec_H264, /*bLowLatency=*/true,
                                               /*bDeviceFramePitched=*/false,
                                               /*pCropRect=*/nullptr,
                                               /*pResizeDim=*/nullptr,
                                               /*bExtractSEIMessage=*/false,
                                               /*nMaxWidth=*/0,
                                               /*nMaxHeight=*/0,
                                               /*nClockRate=*/1000,
                                               /*bForceZeroLatency=*/true);
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
    decoder_.reset();
    if (rgba_buffer_ != nullptr)
    {
        cudaFree(rgba_buffer_);
        rgba_buffer_ = nullptr;
    }
    if (cu_context_ != nullptr)
    {
        cuDevicePrimaryCtxRelease(cu_device_);
        cu_context_ = nullptr;
    }
}

void NvdecPlayer::ensure_rgba_buffer(uint32_t width, uint32_t height)
{
    if (rgba_buffer_ != nullptr && rgba_width_ == width && rgba_height_ == height)
    {
        return;
    }
    if (rgba_buffer_ != nullptr)
    {
        cudaFree(rgba_buffer_);
        rgba_buffer_ = nullptr;
    }
    const size_t bytes = static_cast<size_t>(width) * height * 4;
    cuda_check(cudaMalloc(reinterpret_cast<void**>(&rgba_buffer_), bytes), "cudaMalloc(rgba)");
    rgba_width_ = width;
    rgba_height_ = height;
}

bool NvdecPlayer::feed(const uint8_t* data, size_t size)
{
    current_ = DecodedFrame{};
    if (data == nullptr || size == 0)
    {
        return false;
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
    if (n_frames <= 0)
    {
        cu_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent(no-frame)");
        return false;
    }

    uint8_t* nv12 = decoder_->GetLockedFrame();
    if (nv12 == nullptr)
    {
        cu_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent(no-locked)");
        return false;
    }

    const int w = decoder_->GetWidth();
    const int h = decoder_->GetHeight();
    const int pitch = decoder_->GetDeviceFramePitch();
    const int luma_size = decoder_->GetLumaPlaneSize();

    ensure_rgba_buffer(static_cast<uint32_t>(w), static_cast<uint32_t>(h));

    nv12_to_rgba_fullrange_bt601(
        nv12, nv12 + luma_size, pitch, rgba_buffer_, static_cast<int>(rgba_width_) * 4, w, h, /*stream=*/0);
    const cudaError_t kernel_err = cudaGetLastError();
    decoder_->UnlockFrame(&nv12);
    cu_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent(post-convert)");
    if (kernel_err != cudaSuccess)
    {
        throw std::runtime_error(std::string("NvdecPlayer: NV12->RGBA kernel failed: ") + cudaGetErrorString(kernel_err));
    }

    current_.data = rgba_buffer_;
    current_.width = rgba_width_;
    current_.height = rgba_height_;
    current_.pitch = static_cast<size_t>(rgba_width_) * 4;
    return true;
}

} // namespace viz_smoke
