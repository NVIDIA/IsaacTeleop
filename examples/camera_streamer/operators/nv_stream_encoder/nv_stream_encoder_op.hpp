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

#ifndef NV_STREAM_ENCODER_OP_HPP
#define NV_STREAM_ENCODER_OP_HPP

#include "NvEncoder/NvEncoderCuda.h"
#include "holoscan/core/gxf/entity.hpp"
#include "holoscan/core/operator.hpp"
#include "holoscan/utils/cuda_stream_handler.hpp"

#include <cuda.h>
#include <memory>
#include <vector>

namespace isaac_teleop::cam_streamer
{

/**
 * @brief Ultra-low-latency H.264 stream encoder using NVENC.
 *
 * Encodes GPU frames to H.264 NAL units for streaming.
 *
 * Features:
 * - Zero-copy input from GPU tensors (BGRA from ZED -> NVENC directly)
 * - I-frame only encoding for lowest latency and instant recovery
 * - CBR rate control for stable streaming
 * - Supports BGRA input (ZED cameras output BGRA)
 *
 * Input: "frame" - GPU tensor [H,W,4] BGRA uint8
 * Output: "packet" - H.264 NAL units as byte vector (CPU)
 */
class NvStreamEncoderOp : public holoscan::Operator
{
public:
    HOLOSCAN_OPERATOR_FORWARD_ARGS(NvStreamEncoderOp)

    NvStreamEncoderOp() = default;

    void setup(holoscan::OperatorSpec& spec) override;
    void initialize() override;
    void compute(holoscan::InputContext& op_input,
                 holoscan::OutputContext& op_output,
                 holoscan::ExecutionContext& context) override;
    void stop() override;

private:
    bool init_encoder();

    // Parameters
    holoscan::Parameter<int> width_;
    holoscan::Parameter<int> height_;
    holoscan::Parameter<int> bitrate_;
    holoscan::Parameter<int> fps_;
    holoscan::Parameter<int> cuda_device_ordinal_;
    holoscan::Parameter<std::string> input_format_;
    holoscan::Parameter<bool> verbose_;

    holoscan::CudaStreamHandler cuda_stream_handler_;

    // CUDA
    CUcontext cu_context_ = nullptr;
    CUdevice cu_device_;
    cudaStream_t cuda_stream_ = nullptr;

    // Encoder
    std::unique_ptr<NvEncoderCuda> encoder_;
    bool encoder_initialized_ = false;

    // Stats
    uint64_t frame_count_ = 0;
    double last_log_time_ = 0.0;
    uint64_t last_log_count_ = 0;
};

} // namespace isaac_teleop::cam_streamer

#endif /* NV_STREAM_ENCODER_OP_HPP */
