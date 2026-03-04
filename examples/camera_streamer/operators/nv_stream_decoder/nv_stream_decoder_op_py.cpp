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
#include "nv_stream_decoder_op.hpp"

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

class PyNvStreamDecoderOp : public NvStreamDecoderOp
{
public:
    using NvStreamDecoderOp::NvStreamDecoderOp;

    PyNvStreamDecoderOp(holoscan::Fragment* fragment,
                        const py::args& args,
                        int cuda_device_ordinal,
                        std::shared_ptr<holoscan::Allocator> allocator,
                        bool verbose,
                        const std::string& name = "nv_stream_decoder")
        : NvStreamDecoderOp(holoscan::ArgList{ holoscan::Arg{ "cuda_device_ordinal", cuda_device_ordinal },
                                               holoscan::Arg{ "allocator", allocator },
                                               holoscan::Arg{ "verbose", verbose } })
    {
        add_positional_condition_and_resource_args(this, args);
        name_ = name;
        fragment_ = fragment;
        spec_ = std::make_shared<holoscan::OperatorSpec>(fragment);
        setup(*spec_.get());
    }
};

PYBIND11_MODULE(nv_stream_decoder, m)
{
    m.doc() = "NvStreamDecoderOp - Low-latency H.264 GPU decoder";

    py::class_<NvStreamDecoderOp, PyNvStreamDecoderOp, holoscan::Operator, std::shared_ptr<NvStreamDecoderOp>>(
        m, "NvStreamDecoderOp",
        R"doc(
Low-latency H.264 decoder using NVDEC.

Decodes H.264 NAL units and outputs RGB frames.

Parameters
----------
fragment : Fragment
    Parent fragment.
cuda_device_ordinal : int
    CUDA device (default: 0).
allocator : Allocator
    Output buffer allocator.
verbose : bool
    Enable verbose logging (default: False).
name : str
    Operator name (default: "nv_stream_decoder").
)doc")
        .def(py::init<holoscan::Fragment*, const py::args&, int, std::shared_ptr<holoscan::Allocator>, bool,
                      const std::string&>(),
             "fragment"_a, "cuda_device_ordinal"_a = 0, "allocator"_a, "verbose"_a = false,
             "name"_a = "nv_stream_decoder"s)
        .def("initialize", &NvStreamDecoderOp::initialize)
        .def("setup", &NvStreamDecoderOp::setup, "spec"_a);
}

} // namespace isaac_teleop::cam_streamer
