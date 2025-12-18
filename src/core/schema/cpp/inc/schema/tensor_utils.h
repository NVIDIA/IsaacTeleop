// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Utility functions for working with TensorT native types.

#pragma once

#include <schema/tensor_generated.h>

#include <cstring>
#include <memory>
#include <vector>

namespace core
{

// Creates a TensorT from a vector of float values.
inline std::unique_ptr<TensorT> make_cpu_tensor(const std::vector<float>& values)
{
    auto tensor = std::make_unique<TensorT>();
    tensor->data.resize(values.size() * sizeof(float));
    std::memcpy(tensor->data.data(), values.data(), values.size() * sizeof(float));
    tensor->shape = { static_cast<int64_t>(values.size()) };
    tensor->dtype = DLDataType(DLDataTypeCode_kDLFloat, 32, 1);
    tensor->device = DLDevice(DLDeviceType_kDLCPU, 0);
    tensor->ndim = 1;
    tensor->strides = { sizeof(float) };
    return tensor;
}

} // namespace core
