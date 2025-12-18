// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Tensor FlatBuffer message.

// Include generated FlatBuffer header.
#include <schema/tensor_generated.h>

#include <catch2/catch_test_macros.hpp>

#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::Tensor::VT_DATA == VT(0));
static_assert(core::Tensor::VT_SHAPE == VT(1));
static_assert(core::Tensor::VT_DTYPE == VT(2));
static_assert(core::Tensor::VT_DEVICE == VT(3));
static_assert(core::Tensor::VT_NDIM == VT(4));
static_assert(core::Tensor::VT_STRIDES == VT(5));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::Tensor>().field())
static_assert(std::is_same_v<TYPE(data), const flatbuffers::Vector<uint8_t>*>);
static_assert(std::is_same_v<TYPE(shape), const flatbuffers::Vector<int64_t>*>);
static_assert(std::is_same_v<TYPE(dtype), const core::DLDataType*>);
static_assert(std::is_same_v<TYPE(device), const core::DLDevice*>);
static_assert(std::is_same_v<TYPE(ndim), uint32_t>);
static_assert(std::is_same_v<TYPE(strides), const flatbuffers::Vector<int64_t>*>);

TEST_CASE("DLDataTypeCode enum values are correct", "[tensor][enum]") {
    SECTION("kDLInt has expected value") {
        CHECK(static_cast<int>(core::DLDataTypeCode_kDLInt) == 0);
    }

    SECTION("kDLUInt has expected value") {
        CHECK(static_cast<int>(core::DLDataTypeCode_kDLUInt) == 1);
    }

    SECTION("kDLFloat has expected value") {
        CHECK(static_cast<int>(core::DLDataTypeCode_kDLFloat) == 2);
    }
}

TEST_CASE("DLDeviceType enum values are correct", "[tensor][enum]") {
    SECTION("kDLUnknown has expected value") {
        // DLDeviceType_kDLUnknown should exist
        CHECK(static_cast<int>(core::DLDeviceType_kDLUnknown) >= 0);
    }

    SECTION("kDLCPU has expected value") {
        CHECK(static_cast<int>(core::DLDeviceType_kDLCPU) == 1);
    }

    SECTION("kDLCUDA has expected value") {
        CHECK(static_cast<int>(core::DLDeviceType_kDLCUDA) == 2);
    }

    SECTION("kDLCUDAHost has expected value") {
        CHECK(static_cast<int>(core::DLDeviceType_kDLCUDAHost) == 3);
    }

    SECTION("kDLCUDAManaged has expected value") {
        CHECK(static_cast<int>(core::DLDeviceType_kDLCUDAManaged) == 13);
    }
}

TEST_CASE("DLDataType struct can be created", "[tensor][struct]") {
    SECTION("float32 data type") {
        core::DLDataType dtype(core::DLDataTypeCode_kDLFloat, 32, 1);

        CHECK(dtype.code() == core::DLDataTypeCode_kDLFloat);
        CHECK(dtype.bits() == 32);
        CHECK(dtype.lanes() == 1);
    }

    SECTION("int64 data type") {
        core::DLDataType dtype(core::DLDataTypeCode_kDLInt, 64, 1);

        CHECK(dtype.code() == core::DLDataTypeCode_kDLInt);
        CHECK(dtype.bits() == 64);
        CHECK(dtype.lanes() == 1);
    }

    SECTION("uint8 data type") {
        core::DLDataType dtype(core::DLDataTypeCode_kDLUInt, 8, 1);

        CHECK(dtype.code() == core::DLDataTypeCode_kDLUInt);
        CHECK(dtype.bits() == 8);
        CHECK(dtype.lanes() == 1);
    }
}

TEST_CASE("DLDevice struct can be created", "[tensor][struct]") {
    SECTION("CUDA device 0") {
        core::DLDevice device(core::DLDeviceType_kDLCUDA, 0);

        CHECK(device.device_type() == core::DLDeviceType_kDLCUDA);
        CHECK(device.device_id() == 0);
    }

    SECTION("CPU device") {
        core::DLDevice device(core::DLDeviceType_kDLCPU, 0);

        CHECK(device.device_type() == core::DLDeviceType_kDLCPU);
        CHECK(device.device_id() == 0);
    }

    SECTION("CUDA device 1") {
        core::DLDevice device(core::DLDeviceType_kDLCUDA, 1);

        CHECK(device.device_type() == core::DLDeviceType_kDLCUDA);
        CHECK(device.device_id() == 1);
    }

    SECTION("CUDA Host memory") {
        core::DLDevice device(core::DLDeviceType_kDLCUDAHost, 0);

        CHECK(device.device_type() == core::DLDeviceType_kDLCUDAHost);
        CHECK(device.device_id() == 0);
    }

    SECTION("CUDA Managed memory") {
        core::DLDevice device(core::DLDeviceType_kDLCUDAManaged, 0);

        CHECK(device.device_type() == core::DLDeviceType_kDLCUDAManaged);
        CHECK(device.device_id() == 0);
    }
}

