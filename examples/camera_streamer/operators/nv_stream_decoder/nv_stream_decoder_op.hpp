/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef NV_STREAM_DECODER_OP_HPP
#define NV_STREAM_DECODER_OP_HPP

#include "NvDecoder/NvDecoder.h"
#include "holoscan/core/gxf/entity.hpp"
#include "holoscan/core/operator.hpp"
#include "holoscan/utils/cuda_stream_handler.hpp"

#include <cuda.h>
#include <memory>
#include <nppdefs.h>

namespace isaac_teleop::cam_streamer
{

/**
 * @brief Low-latency H.264 stream decoder.
 *
 * Decodes H.264 NAL units using NVDEC hardware with zero-latency mode.
 * Outputs RGB frames.
 * Mostly copied from
 * https://github.com/nvidia-holoscan/holohub/blob/main/operators/nvidia_video_codec/nv_video_decoder.hpp
 * The main difference is this operator directly decodes NAL units instead of using demuxer.
 *
 * Input: "packet" - H.264 NAL units as holoscan::Tensor (uint8)
 * Output: "frame" - Decoded RGB frame as Entity containing Tensor [H,W,3] (GPU)
 */
class NvStreamDecoderOp : public holoscan::Operator
{
public:
    HOLOSCAN_OPERATOR_FORWARD_ARGS(NvStreamDecoderOp)

    NvStreamDecoderOp() = default;

    void setup(holoscan::OperatorSpec& spec) override;
    void initialize() override;
    void compute(holoscan::InputContext& op_input,
                 holoscan::OutputContext& op_output,
                 holoscan::ExecutionContext& context) override;
    void stop() override;

private:
    bool init_decoder(const uint8_t* data, size_t size);

    // Parameters
    holoscan::Parameter<int> cuda_device_ordinal_;
    holoscan::Parameter<std::shared_ptr<holoscan::Allocator>> allocator_;
    holoscan::Parameter<bool> verbose_;

    holoscan::CudaStreamHandler cuda_stream_handler_;

    // CUDA
    CUcontext cu_context_ = nullptr;
    CUdevice cu_device_ = -1;
    NppStreamContext npp_ctx_{};

    // Decoder
    std::unique_ptr<NvDecoder> decoder_;
    bool decoder_initialized_ = false;

    // Stats
    uint64_t frame_count_ = 0;
    int video_width_ = 0;
    int video_height_ = 0;
};

} // namespace isaac_teleop::cam_streamer

#endif /* NV_STREAM_DECODER_OP_HPP */
