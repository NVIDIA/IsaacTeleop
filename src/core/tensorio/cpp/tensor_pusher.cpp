// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/tensorio/tensor_pusher.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{
namespace tensorio
{

std::unique_ptr<TensorPusher> TensorPusher::create(const OpenXRSessionHandles& handles,
                                                   const TensorCollectionConfig& config)
{
    return std::unique_ptr<TensorPusher>(new TensorPusher(handles, config));
}

TensorPusher::TensorPusher(const OpenXRSessionHandles& handles, const TensorCollectionConfig& config)
    : m_handles(handles), m_identifier(config.identifier)
{
    initialize_extension_functions();
    create_tensor_collection(config);
}

TensorPusher::~TensorPusher()
{
    if (m_push_tensor != XR_NULL_HANDLE && m_destroy_fn != nullptr)
    {
        XrResult result = m_destroy_fn(m_push_tensor);
        if (result != XR_SUCCESS)
        {
            std::cerr << "TensorPusher: Warning: Failed to destroy push tensor collection, result=" << result
                      << std::endl;
        }
    }
}

void TensorPusher::initialize_extension_functions()
{
    if (m_handles.xrGetInstanceProcAddr == nullptr)
    {
        throw std::runtime_error("TensorPusher: xrGetInstanceProcAddr is null");
    }

    XrResult result;

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrCreatePushTensorCollectionNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_fn));
    if (result != XR_SUCCESS || m_create_fn == nullptr)
    {
        throw std::runtime_error("TensorPusher: Failed to get xrCreatePushTensorCollectionNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrPushTensorCollectionDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_push_fn));
    if (result != XR_SUCCESS || m_push_fn == nullptr)
    {
        throw std::runtime_error("TensorPusher: Failed to get xrPushTensorCollectionDataNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrDestroyPushTensorCollectionNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_fn));
    if (result != XR_SUCCESS || m_destroy_fn == nullptr)
    {
        throw std::runtime_error("TensorPusher: Failed to get xrDestroyPushTensorCollectionNV function pointer");
    }
}

void TensorPusher::create_tensor_collection(const TensorCollectionConfig& config)
{
    // Build tensor create info array
    std::vector<XrPushTensorCreateInfoNV> tensor_infos;
    std::vector<XrPushTensorDlpackCreateInfoNV> dlpack_infos;

    tensor_infos.reserve(config.tensors.size());
    dlpack_infos.reserve(config.tensors.size());

    for (const auto& tensor : config.tensors)
    {
        XrPushTensorCreateInfoNV tensor_info{};
        tensor_info.type = XR_TYPE_PUSH_TENSOR_CREATE_INFO_NV;
        tensor_info.next = nullptr;
        tensor_info.properties.dataType = tensor.data_type;
        tensor_info.properties.dataTypeSize = tensor.data_type_size;
        tensor_info.properties.offset = 0; // Will be computed by runtime
        std::strncpy(tensor_info.properties.identifier, tensor.identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
        tensor_info.properties.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';

        if (tensor.dlpack_info.has_value() && tensor.data_type == XR_TENSOR_DATA_TYPE_DLPACK_NV)
        {
            const auto& dlpack = tensor.dlpack_info.value();

            XrPushTensorDlpackCreateInfoNV dlpack_info{};
            dlpack_info.type = XR_TYPE_PUSH_TENSOR_DLPACK_CREATE_INFO_NV;
            dlpack_info.next = nullptr;
            dlpack_info.data.versionMajor = dlpack.version_major;
            dlpack_info.data.versionMinor = dlpack.version_minor;
            dlpack_info.data.dtype = dlpack.dtype;
            dlpack_info.data.ndim = dlpack.ndim;
            dlpack_info.data.byte_offset = dlpack.byte_offset;

            for (int32_t i = 0; i < dlpack.ndim && i < XR_MAX_TENSOR_DLPACK_DIMENSIONS; ++i)
            {
                dlpack_info.data.shape[i] = dlpack.shape[i];
                dlpack_info.data.strides[i] = dlpack.strides[i];
            }

            dlpack_infos.push_back(dlpack_info);
            tensor_info.next = &dlpack_infos.back();
        }

        tensor_infos.push_back(tensor_info);
    }

    // Create collection info
    XrPushTensorCollectionCreateInfoNV create_info{};
    create_info.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_INFO_NV;
    create_info.next = nullptr;
    create_info.tensors = tensor_infos.data();
    create_info.data.tensorCount = static_cast<uint32_t>(tensor_infos.size());
    create_info.data.totalSampleSize = config.compute_total_sample_size();
    std::strncpy(create_info.data.identifier, config.identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
    create_info.data.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';
    std::strncpy(create_info.data.localizedName, config.localized_name.c_str(), XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1);
    create_info.data.localizedName[XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1] = '\0';
    std::memset(&create_info.data.uuid, 0, sizeof(create_info.data.uuid));

    // Create the tensor collection
    XrPushTensorCollectionCreateResultNV create_result{};
    create_result.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_RESULT_NV;
    create_result.next = nullptr;

    XrResult result = m_create_fn(m_handles.session, &create_info, &create_result, &m_push_tensor);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("TensorPusher: Failed to create push tensor collection, result=" +
                                 std::to_string(result));
    }

    m_tensor_collection_id = create_result.tensorCollectionId;
}

bool TensorPusher::push(const uint8_t* buffer, uint32_t buffer_size, XrTime timestamp, uint64_t raw_device_timestamp)
{
    if (m_push_tensor == XR_NULL_HANDLE || m_push_fn == nullptr)
    {
        return false;
    }

    // Generate timestamps if not provided
    if (timestamp == 0 || raw_device_timestamp == 0)
    {
        auto now = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
        if (timestamp == 0)
        {
            timestamp = static_cast<XrTime>(ns);
        }
        if (raw_device_timestamp == 0)
        {
            raw_device_timestamp = static_cast<uint64_t>(ns);
        }
    }

    XrPushTensorCollectionDataNV tensor_data{};
    tensor_data.type = XR_TYPE_PUSH_TENSOR_COLLECTION_DATA_NV;
    tensor_data.next = nullptr;
    tensor_data.timestamp = timestamp;
    tensor_data.rawDeviceTimestamp = raw_device_timestamp;
    tensor_data.buffer = buffer;
    tensor_data.bufferSize = buffer_size;

    XrResult result = m_push_fn(m_push_tensor, &tensor_data);
    if (result != XR_SUCCESS)
    {
        std::cerr << "TensorPusher: Failed to push tensor data, result=" << result << std::endl;
        return false;
    }

    return true;
}

} // namespace tensorio
} // namespace core
