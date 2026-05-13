// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "h264_encoder.hpp"

#include <cstring>
#include <sstream>
#include <stdexcept>

#include <cuda.h>
#include <cuda_runtime.h>

#include "NvEncoder/NvEncoderCuda.h"

namespace camera_viz::codec
{

namespace
{

inline void check_cu(CUresult result, const char* what)
{
    if (result != CUDA_SUCCESS)
    {
        const char* err = nullptr;
        cuGetErrorString(result, &err);
        std::ostringstream os;
        os << "H264Encoder: " << what << " failed: " << (err ? err : "unknown");
        throw std::runtime_error(os.str());
    }
}

NV_ENC_BUFFER_FORMAT to_nvenc_format(PixelFormat fmt)
{
    // NVENC's naming convention is the BIG-endian byte order, so a
    // little-endian layout of R,G,B,A in memory is what NVENC calls ABGR
    // (A in the high byte = last in memory). See nvEncodeAPI.h.
    switch (fmt)
    {
        case PixelFormat::kRGBA8:
            return NV_ENC_BUFFER_FORMAT_ABGR;
        case PixelFormat::kBGRA8:
            return NV_ENC_BUFFER_FORMAT_ARGB;
    }
    throw std::runtime_error("H264Encoder: unsupported pixel format");
}

} // namespace

struct H264Encoder::Impl
{
    EncoderConfig cfg;

    CUdevice cu_device = 0;
    CUcontext cu_context = nullptr;
    std::unique_ptr<NvEncoderCuda> encoder;

    Impl(const EncoderConfig& c) : cfg(c)
    {
        if (cfg.width == 0 || cfg.height == 0)
        {
            throw std::runtime_error("H264Encoder: width/height must be > 0");
        }
        if (cfg.width % 2 != 0 || cfg.height % 2 != 0)
        {
            // NVENC's internal RGBA→YUV converter assumes 4:2:0 chroma,
            // which requires even dimensions. Reject early with a
            // useful error rather than at EncodeFrame() time.
            std::ostringstream os;
            os << "H264Encoder: width and height must be even (got " << cfg.width << "x" << cfg.height << ")";
            throw std::runtime_error(os.str());
        }
        if (cfg.fps == 0)
        {
            throw std::runtime_error("H264Encoder: fps must be > 0");
        }

        check_cu(cuInit(0), "cuInit");
        check_cu(cuDeviceGet(&cu_device, cfg.gpu_id), "cuDeviceGet");
        check_cu(cuDevicePrimaryCtxRetain(&cu_context, cu_device), "cuDevicePrimaryCtxRetain");

        check_cu(cuCtxPushCurrent(cu_context), "cuCtxPushCurrent");
        try
        {
            // nExtraOutputDelay=0 is the entire point of this port —
            // PyNvVideoCodec defaults this to 3, holding 3 frames of
            // bitstream before emitting (~100 ms at 30 fps).
            // m_nEncoderBuffer = frameIntervalP + lookaheadDepth + extraOutputDelay
            //                  = 1 + 0 + 0 = 1
            // m_nOutputDelay = m_nEncoderBuffer - 1 = 0 → emit every frame.
            constexpr uint32_t kExtraOutputDelay = 0;
            encoder = std::make_unique<NvEncoderCuda>(
                cu_context, cfg.width, cfg.height, to_nvenc_format(cfg.pixel_format), kExtraOutputDelay);

            NV_ENC_INITIALIZE_PARAMS init_params = {};
            NV_ENC_CONFIG enc_config = {};
            init_params.version = NV_ENC_INITIALIZE_PARAMS_VER;
            enc_config.version = NV_ENC_CONFIG_VER;
            init_params.encodeConfig = &enc_config;

            // P4 + ULTRA_LOW_LATENCY tuning — camera_streamer's reference.
            encoder->CreateDefaultEncoderParams(&init_params,
                                                NV_ENC_CODEC_H264_GUID,
                                                NV_ENC_PRESET_P4_GUID,
                                                NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY);

            init_params.frameRateNum = cfg.fps;
            init_params.frameRateDen = 1;

            // CBR with 2-frame VBV — matches REF NvStreamEncoderOp.
            enc_config.rcParams.rateControlMode = NV_ENC_PARAMS_RC_CBR;
            enc_config.rcParams.averageBitRate = cfg.bitrate_bps;
            enc_config.rcParams.maxBitRate = static_cast<uint32_t>(cfg.bitrate_bps * 1.2);
            const uint32_t frame_bits = cfg.bitrate_bps / cfg.fps;
            enc_config.rcParams.vbvBufferSize = frame_bits * 2;
            enc_config.rcParams.vbvInitialDelay = frame_bits * 2;

            // No B-frames.
            enc_config.frameIntervalP = 1;

            auto& h264 = enc_config.encodeCodecConfig.h264Config;
            const uint32_t idr = cfg.gop != 0 ? cfg.gop : cfg.fps * 5;
            h264.idrPeriod = idr;
            // SPS/PPS at every IDR — lets late-joining receivers re-init
            // without waiting for a fresh stream.
            h264.repeatSPSPPS = 1;
            h264.sliceMode = 0;
            h264.sliceModeData = 0;
            h264.enableIntraRefresh = 0;
            h264.maxNumRefFrames = 0;

            encoder->CreateEncoder(&init_params);
        }
        catch (...)
        {
            cuCtxPopCurrent(nullptr);
            if (cu_context)
            {
                cuDevicePrimaryCtxRelease(cu_device);
                cu_context = nullptr;
            }
            throw;
        }
        check_cu(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
    }

    ~Impl()
    {
        if (encoder)
        {
            try
            {
                cuCtxPushCurrent(cu_context);
                std::vector<NvEncOutputFrame> flush;
                encoder->EndEncode(flush);
                cuCtxPopCurrent(nullptr);
            }
            catch (...)
            {
                // Swallow — dtor cleanup, nothing useful to surface.
            }
            encoder.reset();
        }
        if (cu_context)
        {
            cuDevicePrimaryCtxRelease(cu_device);
            cu_context = nullptr;
        }
    }

    std::vector<uint8_t> encode_one(uintptr_t rgba_ptr, std::size_t row_pitch_bytes)
    {
        // NvEncoderCuda::CopyToDeviceFrame expects pitch as int; pass 0
        // to mean "tightly packed". Forward any explicit pitch only when
        // it's not the natural pitch — saves an awkward static_cast.
        const std::size_t natural_pitch = static_cast<std::size_t>(cfg.width) * 4u;
        const int src_pitch = (row_pitch_bytes == 0 || row_pitch_bytes == natural_pitch)
                                  ? 0
                                  : static_cast<int>(row_pitch_bytes);

        check_cu(cuCtxPushCurrent(cu_context), "cuCtxPushCurrent");
        std::vector<NvEncOutputFrame> packets;
        try
        {
            const NvEncInputFrame* in = encoder->GetNextInputFrame();
            if (!in)
            {
                throw std::runtime_error("H264Encoder: GetNextInputFrame returned null");
            }
            NvEncoderCuda::CopyToDeviceFrame(cu_context,
                                             reinterpret_cast<void*>(rgba_ptr),
                                             src_pitch,
                                             reinterpret_cast<CUdeviceptr>(in->inputPtr),
                                             static_cast<int>(in->pitch),
                                             encoder->GetEncodeWidth(),
                                             encoder->GetEncodeHeight(),
                                             CU_MEMORYTYPE_DEVICE,
                                             in->bufferFormat,
                                             in->chromaOffsets,
                                             in->numChromaPlanes);
            encoder->EncodeFrame(packets);
        }
        catch (...)
        {
            cuCtxPopCurrent(nullptr);
            throw;
        }
        check_cu(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");

        // With extraOutputDelay=0 and bf=0, each EncodeFrame returns at
        // most one packet. Concatenate just in case some preset ever
        // returns more (defensive — NVENC docs don't guarantee 1).
        std::vector<uint8_t> out;
        std::size_t total = 0;
        for (const auto& p : packets)
            total += p.frame.size();
        out.reserve(total);
        for (const auto& p : packets)
            out.insert(out.end(), p.frame.begin(), p.frame.end());
        return out;
    }

    std::vector<uint8_t> flush()
    {
        if (!encoder)
            return {};
        check_cu(cuCtxPushCurrent(cu_context), "cuCtxPushCurrent");
        std::vector<NvEncOutputFrame> packets;
        try
        {
            encoder->EndEncode(packets);
        }
        catch (...)
        {
            cuCtxPopCurrent(nullptr);
            throw;
        }
        check_cu(cuCtxPopCurrent(nullptr), "cuCtxPopCurrent");
        std::vector<uint8_t> out;
        std::size_t total = 0;
        for (const auto& p : packets)
            total += p.frame.size();
        out.reserve(total);
        for (const auto& p : packets)
            out.insert(out.end(), p.frame.begin(), p.frame.end());
        return out;
    }
};

H264Encoder::H264Encoder(const EncoderConfig& cfg) : impl_(std::make_unique<Impl>(cfg))
{
}

H264Encoder::~H264Encoder() = default;

std::vector<uint8_t> H264Encoder::encode(uintptr_t rgba_device_ptr, std::size_t row_pitch_bytes)
{
    return impl_->encode_one(rgba_device_ptr, row_pitch_bytes);
}

std::vector<uint8_t> H264Encoder::end_of_stream()
{
    return impl_->flush();
}

uint32_t H264Encoder::width() const noexcept
{
    return impl_->cfg.width;
}

uint32_t H264Encoder::height() const noexcept
{
    return impl_->cfg.height;
}

} // namespace camera_viz::codec
