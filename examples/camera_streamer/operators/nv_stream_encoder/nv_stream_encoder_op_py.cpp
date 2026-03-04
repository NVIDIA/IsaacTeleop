/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "holoscan/core/arg.hpp"
#include "holoscan/core/condition.hpp"
#include "holoscan/core/fragment.hpp"
#include "holoscan/core/operator.hpp"
#include "holoscan/core/operator_spec.hpp"
#include "holoscan/core/resource.hpp"
#include "nv_stream_encoder_op.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>
#include <string>

using std::string_literals::operator""s;
using pybind11::literals::operator""_a;
namespace py = pybind11;

namespace isaac_teleop::cam_streamer
{

inline void add_positional_condition_and_resource_args(holoscan::Operator* op, const py::args& args)
{
    for (auto it = args.begin(); it != args.end(); ++it)
    {
        if (py::isinstance<holoscan::Condition>(*it))
        {
            op->add_arg(it->cast<std::shared_ptr<holoscan::Condition>>());
        }
        else if (py::isinstance<holoscan::Resource>(*it))
        {
            op->add_arg(it->cast<std::shared_ptr<holoscan::Resource>>());
        }
    }
}

class PyNvStreamEncoderOp : public NvStreamEncoderOp
{
public:
    using NvStreamEncoderOp::NvStreamEncoderOp;

    PyNvStreamEncoderOp(holoscan::Fragment* fragment,
                        const py::args& args,
                        int width,
                        int height,
                        int bitrate,
                        int fps,
                        int cuda_device_ordinal,
                        const std::string& input_format,
                        bool verbose,
                        const std::string& name = "nv_stream_encoder")
        : NvStreamEncoderOp(holoscan::ArgList{
              holoscan::Arg{ "width", width }, holoscan::Arg{ "height", height }, holoscan::Arg{ "bitrate", bitrate },
              holoscan::Arg{ "fps", fps }, holoscan::Arg{ "cuda_device_ordinal", cuda_device_ordinal },
              holoscan::Arg{ "input_format", input_format }, holoscan::Arg{ "verbose", verbose } })
    {
        add_positional_condition_and_resource_args(this, args);
        name_ = name;
        fragment_ = fragment;
        spec_ = std::make_shared<holoscan::OperatorSpec>(fragment);
        setup(*spec_.get());
    }
};

PYBIND11_MODULE(nv_stream_encoder, m)
{
    m.doc() = "NvStreamEncoderOp - Ultra-low-latency H.264 GPU encoder for streaming";

    py::class_<NvStreamEncoderOp, PyNvStreamEncoderOp, holoscan::Operator, std::shared_ptr<NvStreamEncoderOp>>(
        m, "NvStreamEncoderOp",
        R"doc(
Ultra-low-latency H.264 encoder using NVENC.

Encodes GPU frames to H.264 NAL units optimized for streaming.
Accepts BGRA input (ZED camera format) and outputs H.264 packets.

Features:
- Zero-copy GPU input
- I-frame only encoding for instant seeking
- Ultra-low-latency tuning
- CBR rate control for stable streaming

Parameters
----------
fragment : Fragment
    Parent fragment.
width : int
    Video width in pixels (required).
height : int
    Video height in pixels (required).
bitrate : int
    Target bitrate in bps (required).
fps : int
    Frame rate (required).
cuda_device_ordinal : int
    CUDA device (default: 0).
input_format : str
    Input pixel format: "bgra" or "rgba" (default: "bgra").
verbose : bool
    Enable verbose logging (default: False).
name : str
    Operator name (default: "nv_stream_encoder").

Input Ports
-----------
frame : Tensor
    GPU tensor [H,W,4] BGRA/RGBA uint8

Output Ports
------------
packet : Tensor
    H.264 NAL units as uint8 tensor (CPU)
)doc")
        .def(py::init<holoscan::Fragment*, const py::args&, int, int, int, int, int, const std::string&, bool,
                      const std::string&>(),
             "fragment"_a, "width"_a, "height"_a, "bitrate"_a, "fps"_a, "cuda_device_ordinal"_a = 0,
             "input_format"_a = "bgra"s, "verbose"_a = false, "name"_a = "nv_stream_encoder"s)
        .def("initialize", &NvStreamEncoderOp::initialize)
        .def("setup", &NvStreamEncoderOp::setup, "spec"_a);
}

} // namespace isaac_teleop::cam_streamer
