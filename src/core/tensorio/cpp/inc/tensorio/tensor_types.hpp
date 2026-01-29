// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <XR_NVX1_tensor_data.h>
#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace core
{
namespace tensorio
{

/*!
 * @brief DLPack tensor metadata.
 *
 * Follows the DLPack convention for tensor metadata.
 * dtype encoding: (code << 8) | bits
 *   - code 0: int, code 1: uint, code 2: float, code 4: bfloat
 *   - e.g., float32 = (2 << 8) | 32 = 544
 */
struct DlpackInfo
{
    uint32_t version_major = 1;
    uint32_t version_minor = 0;
    uint32_t dtype = 0; // (code << 8) | bits
    int32_t ndim = 0;
    std::array<int64_t, XR_MAX_TENSOR_DLPACK_DIMENSIONS> shape{};
    std::array<int64_t, XR_MAX_TENSOR_DLPACK_DIMENSIONS> strides{};
    int64_t byte_offset = 0;

    // Helper to create float32 dtype
    static constexpr uint32_t dtype_float32()
    {
        return (2 << 8) | 32;
    }

    // Helper to create float64 dtype
    static constexpr uint32_t dtype_float64()
    {
        return (2 << 8) | 64;
    }

    // Helper to create int32 dtype
    static constexpr uint32_t dtype_int32()
    {
        return (0 << 8) | 32;
    }

    // Helper to create int64 dtype
    static constexpr uint32_t dtype_int64()
    {
        return (0 << 8) | 64;
    }

    // Helper to create uint8 dtype
    static constexpr uint32_t dtype_uint8()
    {
        return (1 << 8) | 8;
    }
};

/*!
 * @brief Specification for a single tensor within a collection.
 */
struct TensorSpec
{
    std::string identifier;
    XrTensorDataTypeNV data_type = XR_TENSOR_DATA_TYPE_DLPACK_NV;
    uint32_t data_type_size = 0;
    std::optional<DlpackInfo> dlpack_info;
};

/*!
 * @brief Configuration for creating a tensor collection.
 */
struct TensorCollectionConfig
{
    std::string identifier;
    std::string localized_name;
    std::vector<TensorSpec> tensors;
    uint32_t total_sample_size = 0; // Can be computed from tensors if 0

    /*!
     * @brief Compute total sample size from tensor specs.
     * @return Total size in bytes.
     */
    uint32_t compute_total_sample_size() const
    {
        if (total_sample_size > 0)
        {
            return total_sample_size;
        }
        uint32_t size = 0;
        for (const auto& tensor : tensors)
        {
            size += tensor.data_type_size;
        }
        return size;
    }
};

/*!
 * @brief Information about a tensor collection (read from runtime).
 */
struct TensorCollectionInfo
{
    XrTensorCollectionIDNV collection_id = 0;
    std::string identifier;
    std::string localized_name;
    uint32_t tensor_count = 0;
    uint32_t total_sample_size = 0;
    uint32_t sample_batch_stride = 0;
};

/*!
 * @brief Information about a single tensor within a collection.
 */
struct TensorInfo
{
    std::string identifier;
    XrTensorDataTypeNV data_type = XR_TENSOR_DATA_TYPE_UNKNOWN_NV;
    uint32_t data_type_size = 0;
    uint32_t offset = 0;
    std::optional<DlpackInfo> dlpack_info;
};

/*!
 * @brief A tensor data sample with metadata.
 */
struct Sample
{
    int64_t sample_index = 0;
    XrTime timestamp = 0;
    uint64_t raw_device_timestamp = 0;
    XrTime arrival_timestamp = 0;
    std::vector<uint8_t> data;
};

} // namespace tensorio
} // namespace core
