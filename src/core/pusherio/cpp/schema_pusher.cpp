// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <oxr_utils/oxr_funcs.hpp>
#include <pusherio/schema_pusher.hpp>

#include <cassert>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace core
{

// DLPack dtype code for uint8: code=1 (unsigned int), bits=8
// Formula: (code << 8) | bits
static constexpr uint32_t DLPACK_DTYPE_UINT8 = (1 << 8) | 8;

SchemaPusher::SchemaPusher(const OpenXRSessionHandles& handles, SchemaPusherConfig config)
    : m_config(std::move(config)), m_time_converter(handles)
{
    // Validate handles
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.xrGetInstanceProcAddr && "xrGetInstanceProcAddr cannot be null");

    // Initialize extension functions using the provided xrGetInstanceProcAddr
    initialize_push_tensor_functions(handles);

    // Create the tensor collection
    create_tensor_collection(handles);

    std::cout << "SchemaPusher initialized for collection: " << m_config.collection_id << std::endl;
}

SchemaPusher::~SchemaPusher()
{
    // m_push_tensor is guaranteed to be non-null by create_tensor_collection(), or the constructor would have thrown.
    assert(m_push_tensor != XR_NULL_HANDLE && m_destroy_fn != nullptr);

    // Destroy the push tensor collection
    XrResult result = m_destroy_fn(m_push_tensor);
    if (result != XR_SUCCESS)
    {
        std::cerr << "Warning: Failed to destroy push tensor collection, result=" << result << std::endl;
    }
}

void SchemaPusher::push_buffer(const uint8_t* buffer,
                               size_t size,
                               int64_t sample_time_device_clock_ns,
                               int64_t sample_time_common_clock_ns)
{
    // Validate that the serialized size fits within our declared buffer
    if (size > m_config.max_flatbuffer_size)
    {
        throw std::runtime_error("Serialized data size (" + std::to_string(size) +
                                 " bytes) exceeds max_flatbuffer_size (" +
                                 std::to_string(m_config.max_flatbuffer_size) + " bytes)");
    }

    // Create padded buffer to match declared tensor size
    // The DLPack tensor is declared as uint8[max_flatbuffer_size], so we need to pad
    std::vector<uint8_t> padded_buffer(m_config.max_flatbuffer_size, 0);
    std::memcpy(padded_buffer.data(), buffer, size);

    // Calculate available_time_common_clock (system monotonic time at push time)
    // TODO: available_time_common_clock is computed here but dropped because the
    // tensor API (XrPushTensorCollectionDataNV) only has timestamp and
    // rawDeviceTimestamp fields. When the tensor API supports a third timestamp
    // field, plumb available_time through.
    [[maybe_unused]] auto available_time_common_clock_ns =
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();

    // Convert sample common clock time to XrTime for the tensor header
    XrTime xr_time = m_time_converter.convert_monotonic_ns_to_xrtime(sample_time_common_clock_ns);

    // Prepare push data structure
    XrPushTensorCollectionDataNV tensorData{};
    tensorData.type = XR_TYPE_PUSH_TENSOR_COLLECTION_DATA_NV;
    tensorData.next = nullptr;
    tensorData.timestamp = xr_time;
    tensorData.rawDeviceTimestamp = static_cast<uint64_t>(sample_time_device_clock_ns);
    tensorData.buffer = padded_buffer.data();
    tensorData.bufferSize = static_cast<uint32_t>(m_config.max_flatbuffer_size);

    // Push the data
    XrResult result = m_push_fn(m_push_tensor, &tensorData);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("Failed to push tensor data, result=" + std::to_string(result));
    }
}

const SchemaPusherConfig& SchemaPusher::config() const
{
    return m_config;
}

void SchemaPusher::initialize_push_tensor_functions(const OpenXRSessionHandles& handles)
{
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrCreatePushTensorCollectionNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_create_fn));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrPushTensorCollectionDataNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_push_fn));
    loadExtensionFunction(handles.instance, handles.xrGetInstanceProcAddr, "xrDestroyPushTensorCollectionNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_fn));
}

void SchemaPusher::create_tensor_collection(const OpenXRSessionHandles& handles)
{
    // Set up DLPack tensor properties for a 1D uint8 array (byte buffer for FlatBuffer)
    XrPushTensorDlpackCreateInfoNV dlpackInfo{};
    dlpackInfo.type = XR_TYPE_PUSH_TENSOR_DLPACK_CREATE_INFO_NV;
    dlpackInfo.next = nullptr;
    dlpackInfo.data.versionMajor = 1;
    dlpackInfo.data.versionMinor = 0;
    dlpackInfo.data.dtype = DLPACK_DTYPE_UINT8;
    dlpackInfo.data.ndim = 1;
    dlpackInfo.data.shape[0] = static_cast<int64_t>(m_config.max_flatbuffer_size);
    dlpackInfo.data.strides[0] = sizeof(uint8_t);
    dlpackInfo.data.byte_offset = 0;

    // Create tensor info with DLPack properties chained
    XrPushTensorCreateInfoNV tensorInfo{};
    tensorInfo.type = XR_TYPE_PUSH_TENSOR_CREATE_INFO_NV;
    tensorInfo.next = &dlpackInfo;
    tensorInfo.properties.dataType = XR_TENSOR_DATA_TYPE_DLPACK_NV;
    tensorInfo.properties.dataTypeSize = m_config.max_flatbuffer_size;
    tensorInfo.properties.offset = 0;
    std::strncpy(tensorInfo.properties.identifier, m_config.tensor_identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
    tensorInfo.properties.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';

    // Create tensor collection with one tensor
    XrPushTensorCollectionCreateInfoNV createInfo{};
    createInfo.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_INFO_NV;
    createInfo.next = nullptr;
    createInfo.tensors = &tensorInfo;
    createInfo.data.tensorCount = 1;
    createInfo.data.totalSampleSize = m_config.max_flatbuffer_size;
    std::strncpy(createInfo.data.identifier, m_config.collection_id.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
    createInfo.data.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';
    std::strncpy(createInfo.data.localizedName, m_config.localized_name.c_str(), XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1);
    createInfo.data.localizedName[XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1] = '\0';
    // Zero out UUID (optional, runtime may assign)
    std::memset(&createInfo.data.uuid, 0, sizeof(createInfo.data.uuid));

    // Create the tensor collection
    XrPushTensorCollectionCreateResultNV createResult{};
    createResult.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_RESULT_NV;
    createResult.next = nullptr;

    XrResult result = m_create_fn(handles.session, &createInfo, &createResult, &m_push_tensor);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("Failed to create push tensor collection, result=" + std::to_string(result));
    }
}

} // namespace core
