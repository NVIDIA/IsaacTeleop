/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "nv_stream_decoder_op.hpp"

#include "gxf/multimedia/video.hpp"
#include "gxf/std/allocator.hpp"
#include "gxf/std/tensor.hpp"
#include "holoscan/core/domain/tensor.hpp"
#include "holoscan/core/execution_context.hpp"
#include "holoscan/core/gxf/entity.hpp"
#include "holoscan/core/io_context.hpp"

#include <cuda.h>
#include <cuda_runtime.h>
#include <nppi_color_conversion.h>

inline void cuda_check(CUresult result)
{
    if (result != CUDA_SUCCESS)
    {
        const char* err;
        cuGetErrorString(result, &err);
        HOLOSCAN_LOG_ERROR("CUDA error: {}", err);
        throw std::runtime_error("CUDA error");
    }
}

namespace isaac_teleop::cam_streamer
{

void NvStreamDecoderOp::setup(holoscan::OperatorSpec& spec)
{
    spec.input<std::shared_ptr<holoscan::Tensor>>("packet").condition(holoscan::ConditionType::kMessageAvailable);
    spec.output<holoscan::gxf::Entity>("frame").condition(holoscan::ConditionType::kNone);

    spec.param(cuda_device_ordinal_, "cuda_device_ordinal", "CUDA Device", "CUDA device ordinal", 0);
    spec.param(allocator_, "allocator", "Allocator", "Output buffer allocator");
    spec.param(verbose_, "verbose", "Verbose", "Enable verbose logging", false);

    cuda_stream_handler_.define_params(spec);
}

void NvStreamDecoderOp::initialize()
{
    holoscan::Operator::initialize();

    cuda_check(cuInit(0));
    cuda_check(cuDeviceGet(&cu_device_, cuda_device_ordinal_.get()));
    cuda_check(cuDevicePrimaryCtxRetain(&cu_context_, cu_device_));

    // Initialize NPP stream context manually.
    {
        npp_ctx_.hStream = 0; // Default (NULL) stream.

        cudaGetDevice(&npp_ctx_.nCudaDeviceId);

        cudaDeviceGetAttribute(
            &npp_ctx_.nCudaDevAttrComputeCapabilityMajor, cudaDevAttrComputeCapabilityMajor, npp_ctx_.nCudaDeviceId);
        cudaDeviceGetAttribute(
            &npp_ctx_.nCudaDevAttrComputeCapabilityMinor, cudaDevAttrComputeCapabilityMinor, npp_ctx_.nCudaDeviceId);

        cudaStreamGetFlags(npp_ctx_.hStream, &npp_ctx_.nStreamFlags);

        cudaDeviceProp deviceProperties;
        cudaGetDeviceProperties(&deviceProperties, npp_ctx_.nCudaDeviceId);

        npp_ctx_.nMultiProcessorCount = deviceProperties.multiProcessorCount;
        npp_ctx_.nMaxThreadsPerMultiProcessor = deviceProperties.maxThreadsPerMultiProcessor;
        npp_ctx_.nMaxThreadsPerBlock = deviceProperties.maxThreadsPerBlock;
        npp_ctx_.nSharedMemPerBlock = deviceProperties.sharedMemPerBlock;
    }

    if (verbose_.get())
    {
        char name[256];
        cuDeviceGetName(name, sizeof(name), cu_device_);
        HOLOSCAN_LOG_INFO("NvStreamDecoderOp on GPU: {}", name);
    }
}

bool NvStreamDecoderOp::init_decoder(const uint8_t* data, size_t size)
{
    if (decoder_initialized_)
        return true;

    cuda_check(cuCtxPushCurrent(cu_context_));

    try
    {
        decoder_ = std::make_unique<NvDecoder>(cu_context_,
                                               true, // bUseDeviceFrame - decode to GPU memory
                                               cudaVideoCodec_H264, // eCodec
                                               true, // bLowLatency
                                               false, // bDeviceFramePitched
                                               nullptr, nullptr, // pCropRect, pResizeDim
                                               false, // bExtractSEIMessage - don't extract SEI metadata
                                               0, // nMaxWidth - 0 = auto-detect from stream
                                               0, // nMaxHeight - 0 = auto-detect from stream
                                               1000, // nClockRate - timestamp clock rate
                                               true); // bForceZeroLatency

        decoder_initialized_ = true;
        if (verbose_.get())
        {
            HOLOSCAN_LOG_INFO("Decoder initialized (zero-latency H.264)");
        }
    }
    catch (const NVDECException& e)
    {
        HOLOSCAN_LOG_ERROR("Decoder init failed: {}", e.what());
        cuda_check(cuCtxPopCurrent(nullptr));
        return false;
    }

    cuda_check(cuCtxPopCurrent(nullptr));
    return true;
}

void NvStreamDecoderOp::compute(holoscan::InputContext& op_input,
                                holoscan::OutputContext& op_output,
                                holoscan::ExecutionContext& context)
{
    auto tensor = op_input.receive<std::shared_ptr<holoscan::Tensor>>("packet");
    if (!tensor || !tensor.value())
        return;

    auto data_ptr = static_cast<uint8_t*>(tensor.value()->data());
    auto data_size = tensor.value()->size();
    if (data_size == 0)
        return;

    if (!init_decoder(data_ptr, data_size))
        return;

    // Decode
    cuda_check(cuCtxPushCurrent(cu_context_));
    int nFrames = 0;
    try
    {
        nFrames = decoder_->Decode(data_ptr, static_cast<int>(data_size));
    }
    catch (const NVDECException& e)
    {
        HOLOSCAN_LOG_ERROR("Decode failed: {}", e.what());
        cuCtxPopCurrent(nullptr);
        return;
    }
    cuda_check(cuCtxPopCurrent(nullptr));

    if (nFrames == 0)
        return;

    uint8_t* pFrame = decoder_->GetLockedFrame();
    if (!pFrame)
        return;

    int width = decoder_->GetWidth();
    int height = decoder_->GetHeight();
    int pitch = decoder_->GetDeviceFramePitch();
    int lumaSize = decoder_->GetLumaPlaneSize();

    if (video_width_ != width || video_height_ != height)
    {
        video_width_ = width;
        video_height_ = height;
        if (verbose_.get())
        {
            HOLOSCAN_LOG_INFO("Video: {}x{}", width, height);
        }
    }

    auto allocator = nvidia::gxf::Handle<nvidia::gxf::Allocator>::Create(context.context(), allocator_->gxf_cid());
    auto output = nvidia::gxf::Entity::New(context.context());
    if (!output)
    {
        decoder_->UnlockFrame(&pFrame);
        throw std::runtime_error("Failed to create output entity");
    }

    // Output RGB tensor [height, width, 3] in HWC format
    auto out_tensor = output.value().add<nvidia::gxf::Tensor>("");
    if (!out_tensor)
    {
        decoder_->UnlockFrame(&pFrame);
        throw std::runtime_error("Failed to add Tensor to output entity");
    }

    nvidia::gxf::Shape shape{ static_cast<int32_t>(height), static_cast<int32_t>(width), 3 };
    out_tensor.value()->reshapeCustom(shape, nvidia::gxf::PrimitiveType::kUnsigned8,
                                      nvidia::gxf::PrimitiveTypeSize(nvidia::gxf::PrimitiveType::kUnsigned8),
                                      nvidia::gxf::Unexpected{ GXF_UNINITIALIZED_VALUE },
                                      nvidia::gxf::MemoryStorageType::kDevice, allocator.value());

    auto dst = static_cast<uint8_t*>(out_tensor.value()->pointer());

    const Npp8u* pSrc[2] = { pFrame, pFrame + lumaSize };
    NppiSize roi = { width, height };

    NppStatus status = nppiNV12ToRGB_8u_P2C3R_Ctx(pSrc, pitch, dst, width * 3, roi, npp_ctx_);
    if (status != NPP_SUCCESS)
    {
        HOLOSCAN_LOG_ERROR("NPP NV12->RGB failed: {}", static_cast<int>(status));
        decoder_->UnlockFrame(&pFrame);
        return;
    }

    decoder_->UnlockFrame(&pFrame);

    frame_count_++;

    auto out_entity = holoscan::gxf::Entity(std::move(output.value()));
    op_output.emit(out_entity, "frame");
}

void NvStreamDecoderOp::stop()
{
    decoder_.reset();
    if (cu_context_)
    {
        cuDevicePrimaryCtxRelease(cu_device_);
        cu_context_ = nullptr;
    }
    if (verbose_.get())
    {
        HOLOSCAN_LOG_INFO("NvStreamDecoderOp stopped. Frames: {}", frame_count_);
    }
}

} // namespace isaac_teleop::cam_streamer
