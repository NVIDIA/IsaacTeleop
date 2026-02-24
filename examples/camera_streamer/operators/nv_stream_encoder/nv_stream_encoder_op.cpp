/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "nv_stream_encoder_op.hpp"

#include "dlpack/dlpack.h"
#include "gxf/std/allocator.hpp"
#include "gxf/std/tensor.hpp"
#include "holoscan/core/domain/tensor.hpp"
#include "holoscan/core/domain/tensor_map.hpp"
#include "holoscan/core/execution_context.hpp"
#include "holoscan/core/gxf/entity.hpp"
#include "holoscan/core/io_context.hpp"

#include <chrono>
#include <cstring>
#include <cuda.h>
#include <cuda_runtime.h>

namespace
{

constexpr double STATS_INTERVAL_SEC = 30.0;

inline void cuda_check(CUresult result, const char* msg = "")
{
    if (result != CUDA_SUCCESS)
    {
        const char* err;
        cuGetErrorString(result, &err);
        HOLOSCAN_LOG_ERROR("CUDA error {}: {}", msg, err);
        throw std::runtime_error(std::string("CUDA error: ") + err);
    }
}

inline void cuda_rt_check(cudaError_t result, const char* msg = "")
{
    if (result != cudaSuccess)
    {
        HOLOSCAN_LOG_ERROR("CUDA runtime error {}: {}", msg, cudaGetErrorString(result));
        throw std::runtime_error(std::string("CUDA runtime error: ") + cudaGetErrorString(result));
    }
}

double get_time()
{
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

} // namespace

namespace isaac_teleop::cam_streamer
{

void NvStreamEncoderOp::setup(holoscan::OperatorSpec& spec)
{
    // Input: GPU tensor [H,W,4] BGRA (received as TensorMap from Python)
    spec.input<holoscan::TensorMap>("frame").condition(holoscan::ConditionType::kMessageAvailable);

    // Output: H.264 NAL units as byte vector
    spec.output<std::vector<uint8_t>>("packet").condition(holoscan::ConditionType::kNone);

    spec.param(width_, "width", "Width", "Video width in pixels", 1280);
    spec.param(height_, "height", "Height", "Video height in pixels", 720);
    spec.param(bitrate_, "bitrate", "Bitrate", "Target bitrate in bps", 15000000);
    spec.param(fps_, "fps", "FPS", "Frame rate", 30);
    spec.param(cuda_device_ordinal_, "cuda_device_ordinal", "CUDA Device", "CUDA device ordinal", 0);
    spec.param(input_format_, "input_format", "Input Format", "Input pixel format: bgra or rgba", std::string("bgra"));
    spec.param(verbose_, "verbose", "Verbose", "Enable verbose logging", false);

    cuda_stream_handler_.define_params(spec);
}

void NvStreamEncoderOp::initialize()
{
    holoscan::Operator::initialize();

    cuda_check(cuInit(0), "cuInit");
    cuda_check(cuDeviceGet(&cu_device_, cuda_device_ordinal_.get()), "cuDeviceGet");
    cuda_check(cuDevicePrimaryCtxRetain(&cu_context_, cu_device_), "cuDevicePrimaryCtxRetain");

    // Create CUDA stream for async operations
    cuda_rt_check(cudaStreamCreate(&cuda_stream_), "cudaStreamCreate");

    if (verbose_.get())
    {
        char name[256];
        cuDeviceGetName(name, sizeof(name), cu_device_);
        HOLOSCAN_LOG_INFO("NvStreamEncoderOp on GPU: {} ({}x{}@{}fps, {}Mbps)", name, width_.get(), height_.get(),
                          fps_.get(), bitrate_.get() / 1000000);
    }

    last_log_time_ = get_time();
}

bool NvStreamEncoderOp::init_encoder()
{
    if (encoder_initialized_)
        return true;

    cuda_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent");

    try
    {
        // Create encoder with ARGB input format
        // NVENC handles internal YUV conversion
        encoder_ = std::make_unique<NvEncoderCuda>(cu_context_, width_.get(), height_.get(), NV_ENC_BUFFER_FORMAT_ARGB,
                                                   0 // Use default extra output delay
        );

        // Get codec GUID for H.264
        GUID guidCodec = NV_ENC_CODEC_H264_GUID;

        // P3: low-latency preset for streaming (P1 = fastest, P7 = highest quality)
        GUID guidPreset = NV_ENC_PRESET_P4_GUID;

        // Initialize encoder parameters
        NV_ENC_INITIALIZE_PARAMS initializeParams = {};
        NV_ENC_CONFIG encodeConfig = {};
        initializeParams.version = NV_ENC_INITIALIZE_PARAMS_VER;
        encodeConfig.version = NV_ENC_CONFIG_VER;
        initializeParams.encodeConfig = &encodeConfig;

        // Create default encoder params with ultra low-latency tuning
        encoder_->CreateDefaultEncoderParams(
            &initializeParams, guidCodec, guidPreset, NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY);

        // Override key settings for streaming
        initializeParams.frameRateNum = fps_.get();
        initializeParams.frameRateDen = 1;

        // CBR for streaming
        encodeConfig.rcParams.rateControlMode = NV_ENC_PARAMS_RC_CBR;
        encodeConfig.rcParams.averageBitRate = bitrate_.get();
        encodeConfig.rcParams.maxBitRate = bitrate_.get() * 1.2; // 20% overhead

        // VBV buffer size: 1 frame worth of data for minimum latency
        encodeConfig.rcParams.vbvBufferSize = bitrate_.get() / fps_.get();
        encodeConfig.rcParams.vbvInitialDelay = encodeConfig.rcParams.vbvBufferSize;

        // No B-frames for lowest latency
        encodeConfig.frameIntervalP = 1;

        // H.264 specific settings
        NV_ENC_CONFIG_H264& h264Config = encodeConfig.encodeCodecConfig.h264Config;
        h264Config.idrPeriod = fps_.get(); // Every 1sec IDR for instant seeking/recovery
        h264Config.repeatSPSPPS = 1; // Include SPS/PPS with every IDR
        h264Config.sliceMode = 0;
        h264Config.sliceModeData = 0;

        // Disable features that add latency
        h264Config.enableIntraRefresh = 0;
        h264Config.maxNumRefFrames = 0; // 0 = auto, but we want minimal

        // Create the encoder
        encoder_->CreateEncoder(&initializeParams);

        encoder_initialized_ = true;

        if (verbose_.get())
        {
            HOLOSCAN_LOG_INFO(
                "NVENC encoder initialized (BGRA input, ultra-low-latency H.264, IDR every {}frames)", fps_.get());
        }
    }
    catch (const NVENCException& e)
    {
        HOLOSCAN_LOG_ERROR("NVENC init failed: {}", e.what());
        cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
        return false;
    }
    catch (const std::exception& e)
    {
        HOLOSCAN_LOG_ERROR("Encoder init failed: {}", e.what());
        cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
        return false;
    }

    cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
    return true;
}

void NvStreamEncoderOp::compute(holoscan::InputContext& op_input,
                                holoscan::OutputContext& op_output,
                                holoscan::ExecutionContext& context)
{
    auto tensor_map = op_input.receive<holoscan::TensorMap>("frame");
    if (!tensor_map || tensor_map->empty())
    {
        return;
    }

    // Get the tensor (we expect only one tensor)
    auto& holoscan_tensor = tensor_map->begin()->second;

    void* data_pointer = holoscan_tensor->data();
    auto tensor_shape = holoscan_tensor->shape();

    // Validate input dimensions from holoscan::Tensor
    if (tensor_shape.size() != 3 || tensor_shape[2] != 4)
    {
        HOLOSCAN_LOG_ERROR("Expected [H,W,4] tensor, got ndim={}", tensor_shape.size());
        return;
    }

    int height = static_cast<int>(tensor_shape[0]);
    int width = static_cast<int>(tensor_shape[1]);

    // Verify dimensions match configuration
    if (width != width_.get() || height != height_.get())
    {
        HOLOSCAN_LOG_ERROR("Frame size {}x{} doesn't match configured {}x{}", width, height, width_.get(), height_.get());
        throw std::runtime_error("Encoder dimension mismatch - update config to match camera resolution");
    }

    // Initialize encoder on first frame
    if (!encoder_initialized_ && !init_encoder())
    {
        return;
    }

    // Get data pointer from GXF tensor
    auto data_ptr = static_cast<const uint8_t*>(data_pointer);
    if (!data_ptr)
    {
        HOLOSCAN_LOG_ERROR("Tensor data pointer is null");
        return;
    }

    // Verify data is on GPU (holoscan::Tensor uses DLPack device type)
    auto dl_device = holoscan_tensor->device();
    if (dl_device.device_type != kDLCUDA && dl_device.device_type != kDLCUDAManaged)
    {
        HOLOSCAN_LOG_ERROR("Input tensor must be on GPU (got device_type={})", static_cast<int>(dl_device.device_type));
        return;
    }

    cuda_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent");

    try
    {
        // Get encoder input frame
        const NvEncInputFrame* encoderInputFrame = encoder_->GetNextInputFrame();
        if (!encoderInputFrame)
        {
            HOLOSCAN_LOG_ERROR("Failed to get encoder input frame");
            cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
            return;
        }

        // Copy BGRA data directly to encoder input buffer
        NvEncoderCuda::CopyToDeviceFrame(
            cu_context_, const_cast<void*>(static_cast<const void*>(data_ptr)),
            0, // srcPitch = 0 means use width * 4
            reinterpret_cast<CUdeviceptr>(encoderInputFrame->inputPtr), static_cast<int>(encoderInputFrame->pitch),
            encoder_->GetEncodeWidth(), encoder_->GetEncodeHeight(), CU_MEMORYTYPE_DEVICE,
            encoderInputFrame->bufferFormat, encoderInputFrame->chromaOffsets, encoderInputFrame->numChromaPlanes);

        std::vector<NvEncOutputFrame> vPacket;
        encoder_->EncodeFrame(vPacket);

        cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");

        // Output encoded packets as std::vector<uint8_t>
        if (!vPacket.empty() && !vPacket[0].frame.empty())
        {
            // Copy to output vector
            std::vector<uint8_t> output_data(vPacket[0].frame.begin(), vPacket[0].frame.end());

            if (verbose_.get() && frame_count_ == 0)
            {
                HOLOSCAN_LOG_INFO("NvStreamEncoderOp[{}]: First encoded frame, {} bytes", name(), output_data.size());
            }

            op_output.emit(output_data, "packet");
        }

        frame_count_++;

        if (verbose_.get())
        {
            double now = get_time();
            if (now - last_log_time_ >= STATS_INTERVAL_SEC)
            {
                double fps = (frame_count_ - last_log_count_) / (now - last_log_time_);
                HOLOSCAN_LOG_INFO("NvStreamEncoderOp | fps={:.1f} | total={}", fps, frame_count_);
                last_log_time_ = now;
                last_log_count_ = frame_count_;
            }
        }
    }
    catch (const NVENCException& e)
    {
        HOLOSCAN_LOG_ERROR("NVENC encode failed: {}", e.what());
        cuCtxPopCurrent(nullptr);
        return;
    }
    catch (const std::exception& e)
    {
        HOLOSCAN_LOG_ERROR("Encode error: {}", e.what());
        cuCtxPopCurrent(nullptr);
        return;
    }
}

void NvStreamEncoderOp::stop()
{
    if (encoder_)
    {
        try
        {
            cuda_check(cuCtxPushCurrent(cu_context_), "cuCtxPushCurrent");
            std::vector<NvEncOutputFrame> vPacket;
            encoder_->EndEncode(vPacket);
            cuda_check(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
        }
        catch (...)
        {
            // Ignore errors during shutdown
        }
        encoder_.reset();
    }

    if (cuda_stream_)
    {
        cudaStreamDestroy(cuda_stream_);
        cuda_stream_ = nullptr;
    }

    if (cu_context_)
    {
        cuDevicePrimaryCtxRelease(cu_device_);
        cu_context_ = nullptr;
    }

    if (verbose_.get())
    {
        HOLOSCAN_LOG_INFO("NvStreamEncoderOp stopped. Frames encoded: {}", frame_count_);
    }
}

} // namespace isaac_teleop::cam_streamer
