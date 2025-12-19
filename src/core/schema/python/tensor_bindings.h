// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Python bindings for the Tensor FlatBuffer schema.

#pragma once

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <schema/tensor_generated.h>

#include <memory>
#include <vector>

namespace py = pybind11;

namespace core
{

// Determine DLDataType from buffer format string and itemsize.
// This approach is robust across platforms where format codes for the same
// bit-width type can differ (e.g., 'l' vs 'q' for 64-bit integers on LP64 vs LLP64).
inline DLDataType format_to_dltype(const std::string& format, size_t itemsize)
{
    if (format.empty())
    {
        throw std::runtime_error("Empty format string");
    }

    // The format character indicates the type kind:
    // Signed integers: 'b' (int8), 'h' (int16), 'i' (int32), 'l' (long), 'q' (long long), 'n' (ssize_t)
    // Unsigned integers: 'B' (uint8), 'H' (uint16), 'I' (uint32), 'L' (ulong), 'Q' (ulonglong), 'N' (size_t)
    // Floats: 'e' (float16), 'f' (float32), 'd' (float64)
    char kind = format[0];
    uint8_t bits = static_cast<uint8_t>(itemsize * 8);

    switch (kind)
    {
    // Signed integers
    case 'b':
    case 'h':
    case 'i':
    case 'l':
    case 'q':
    case 'n':
        return DLDataType(DLDataTypeCode_kDLInt, bits, 1);

    // Unsigned integers
    case 'B':
    case 'H':
    case 'I':
    case 'L':
    case 'Q':
    case 'N':
        return DLDataType(DLDataTypeCode_kDLUInt, bits, 1);

    // Floating point
    case 'e':
    case 'f':
    case 'd':
        return DLDataType(DLDataTypeCode_kDLFloat, bits, 1);

    default:
        throw std::runtime_error(std::string("Unsupported numpy dtype format: '") + format + "'");
    }
}

// Helper to create a TensorT from a numpy array.
inline std::unique_ptr<TensorT> numpy_to_tensor(py::array array)
{
    auto tensor = std::make_unique<TensorT>();

    // Ensure array is C-contiguous. Non-contiguous arrays (e.g., slices with
    // strides) have gaps in memory that can't be copied with a simple memcpy.
    // py::array::c_style requests a C-contiguous layout, making a copy if needed.
    array = py::array::ensure(array, py::array::c_style);
    if (!array)
    {
        throw std::runtime_error("Failed to convert array to C-contiguous layout");
    }

    // Get buffer info.
    py::buffer_info info = array.request();

    // Copy data (now guaranteed to be contiguous).
    tensor->data.resize(info.size * info.itemsize);
    std::memcpy(tensor->data.data(), info.ptr, tensor->data.size());

    // Set shape.
    tensor->shape.reserve(info.ndim);
    for (py::ssize_t i = 0; i < info.ndim; ++i)
    {
        tensor->shape.push_back(static_cast<int64_t>(info.shape[i]));
    }

    // Set strides.
    tensor->strides.reserve(info.ndim);
    for (py::ssize_t i = 0; i < info.ndim; ++i)
    {
        tensor->strides.push_back(static_cast<int64_t>(info.strides[i]));
    }

    // Set ndim.
    tensor->ndim = static_cast<uint32_t>(info.ndim);

    // Set dtype using format kind + itemsize (robust across platforms).
    tensor->dtype = format_to_dltype(info.format, info.itemsize);

    // Default to CPU device.
    tensor->device = DLDevice(DLDeviceType_kDLCPU, 0);

    return tensor;
}

// Helper to convert TensorT to a numpy array.
inline py::array tensor_to_numpy(const TensorT& tensor)
{
    // Determine numpy dtype from DLDataType.
    std::string format;
    size_t itemsize = 0;

    if (tensor.dtype.code() == DLDataTypeCode_kDLFloat)
    {
        if (tensor.dtype.bits() == 32)
        {
            format = py::format_descriptor<float>::format();
            itemsize = sizeof(float);
        }
        else if (tensor.dtype.bits() == 64)
        {
            format = py::format_descriptor<double>::format();
            itemsize = sizeof(double);
        }
    }
    else if (tensor.dtype.code() == DLDataTypeCode_kDLInt)
    {
        if (tensor.dtype.bits() == 32)
        {
            format = py::format_descriptor<int32_t>::format();
            itemsize = sizeof(int32_t);
        }
        else if (tensor.dtype.bits() == 64)
        {
            format = py::format_descriptor<int64_t>::format();
            itemsize = sizeof(int64_t);
        }
    }
    else if (tensor.dtype.code() == DLDataTypeCode_kDLUInt)
    {
        if (tensor.dtype.bits() == 8)
        {
            format = py::format_descriptor<uint8_t>::format();
            itemsize = sizeof(uint8_t);
        }
        else if (tensor.dtype.bits() == 32)
        {
            format = py::format_descriptor<uint32_t>::format();
            itemsize = sizeof(uint32_t);
        }
        else if (tensor.dtype.bits() == 64)
        {
            format = py::format_descriptor<uint64_t>::format();
            itemsize = sizeof(uint64_t);
        }
    }

    if (format.empty())
    {
        throw std::runtime_error("Unsupported tensor dtype for numpy conversion");
    }

    // Build shape and strides vectors.
    std::vector<py::ssize_t> shape(tensor.shape.begin(), tensor.shape.end());
    std::vector<py::ssize_t> strides(tensor.strides.begin(), tensor.strides.end());

    // Create numpy array (copy data).
    py::array result(py::buffer_info(nullptr, // Pointer to buffer (nullptr for allocation).
                                     itemsize, format, static_cast<py::ssize_t>(tensor.ndim), shape, strides));

    // Copy data to the array.
    std::memcpy(result.mutable_data(), tensor.data.data(), tensor.data.size());

    return result;
}

inline void bind_tensor(py::module& m)
{
    // Bind DLDataTypeCode enum.
    py::enum_<DLDataTypeCode>(m, "DLDataTypeCode")
        .value("kDLInt", DLDataTypeCode_kDLInt)
        .value("kDLUInt", DLDataTypeCode_kDLUInt)
        .value("kDLFloat", DLDataTypeCode_kDLFloat);

    // Bind DLDeviceType enum.
    py::enum_<DLDeviceType>(m, "DLDeviceType")
        .value("kDLUnknown", DLDeviceType_kDLUnknown)
        .value("kDLCPU", DLDeviceType_kDLCPU)
        .value("kDLCUDA", DLDeviceType_kDLCUDA)
        .value("kDLCUDAHost", DLDeviceType_kDLCUDAHost)
        .value("kDLCUDAManaged", DLDeviceType_kDLCUDAManaged);

    // Bind DLDataType struct (FlatBuffers structs are immutable, read-only properties).
    py::class_<DLDataType>(m, "DLDataType")
        .def(py::init<>())
        .def(py::init<DLDataTypeCode, uint8_t, uint16_t>(), py::arg("code"), py::arg("bits"), py::arg("lanes") = 1)
        .def_property_readonly("code", &DLDataType::code)
        .def_property_readonly("bits", &DLDataType::bits)
        .def_property_readonly("lanes", &DLDataType::lanes);

    // Bind DLDevice struct (FlatBuffers structs are immutable, read-only properties).
    py::class_<DLDevice>(m, "DLDevice")
        .def(py::init<>())
        .def(py::init<DLDeviceType, int32_t>(), py::arg("device_type"), py::arg("device_id") = 0)
        .def_property_readonly("device_type", &DLDevice::device_type)
        .def_property_readonly("device_id", &DLDevice::device_id);

    // Bind TensorT class.
    py::class_<TensorT, std::unique_ptr<TensorT>>(m, "TensorT")
        .def(py::init<>())
        .def_property(
            "data",
            [](const TensorT& self) -> py::bytes
            { return py::bytes(reinterpret_cast<const char*>(self.data.data()), self.data.size()); },
            [](TensorT& self, py::bytes value)
            {
                std::string str = value;
                self.data.assign(str.begin(), str.end());
            })
        .def_readwrite("shape", &TensorT::shape)
        .def_readwrite("dtype", &TensorT::dtype)
        .def_readwrite("device", &TensorT::device)
        .def_readwrite("ndim", &TensorT::ndim)
        .def_readwrite("strides", &TensorT::strides)
        // Convenience methods for numpy interop.
        .def_static("from_numpy", &numpy_to_tensor, py::arg("array"), "Create a TensorT from a numpy array.")
        .def(
            "to_numpy", [](const TensorT& self) { return tensor_to_numpy(self); },
            "Convert the TensorT to a numpy array.");
}

} // namespace core
