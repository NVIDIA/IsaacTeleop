// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <openxr/openxr.h>
#include <oxr_utils/oxr_time.hpp>
#include <pusherio/schema_pusher.hpp>

#include <XR_NVX1_push_tensor.h>
#include <XR_NVX1_tensor_data.h>
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace core
{

// DLPack dtype code for uint8: code=1 (unsigned int), bits=8
// Formula: (code << 8) | bits
static constexpr uint32_t DLPACK_DTYPE_UINT8 = (1 << 8) | 8;

/*!
 * @brief PIMPL implementation for SchemaPusherBase.
 *
 * Uses externally-provided OpenXR session handles for tensor push operations.
 */
class SchemaPusherBase::Impl
{
public:
    Impl(const OpenXRSessionHandles& handles, SchemaPusherConfig config)
        : m_handles(handles), m_config(std::move(config)), m_time_converter(handles)
    {
        // Validate handles
        assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
        assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
        assert(handles.xrGetInstanceProcAddr && "xrGetInstanceProcAddr cannot be null");

        // Initialize extension functions using the provided xrGetInstanceProcAddr
        initialize_push_tensor_functions();

        // Create the tensor collection
        create_tensor_collection();

        std::cout << "SchemaPusherBase initialized for collection: " << m_config.collection_id << std::endl;
    }

    ~Impl()
    {
        // Destroy the push tensor collection
        if (m_push_tensor != XR_NULL_HANDLE && m_destroy_fn != nullptr)
        {
            XrResult result = m_destroy_fn(m_push_tensor);
            if (result != XR_SUCCESS)
            {
                std::cerr << "Warning: Failed to destroy push tensor collection, result=" << result << std::endl;
            }
        }
    }

    bool push_buffer(const uint8_t* buffer, size_t size)
    {
        // Validate that the serialized size fits within our declared buffer
        if (size > m_config.max_flatbuffer_size)
        {
            std::cerr << "ERROR: Serialized data size (" << size << " bytes) exceeds max_flatbuffer_size ("
                      << m_config.max_flatbuffer_size << " bytes). Skipping push." << std::endl;
            return false;
        }

        // Create padded buffer to match declared tensor size
        // The DLPack tensor is declared as uint8[max_flatbuffer_size], so we need to pad
        std::vector<uint8_t> padded_buffer(m_config.max_flatbuffer_size, 0);
        std::memcpy(padded_buffer.data(), buffer, size);

        // Get current time for timestamps
        XrTime xr_time;
        if (!m_time_converter.get_current_time(xr_time))
        {
            std::cerr << "ERROR: Failed to get current XrTime. Skipping push." << std::endl;
            return false;
        }

        // Prepare push data structure
        XrPushTensorCollectionDataNV tensorData{};
        tensorData.type = XR_TYPE_PUSH_TENSOR_COLLECTION_DATA_NV;
        tensorData.next = nullptr;
        tensorData.timestamp = xr_time;
        tensorData.rawDeviceTimestamp = static_cast<uint64_t>(xr_time);
        tensorData.buffer = padded_buffer.data();
        tensorData.bufferSize = static_cast<uint32_t>(m_config.max_flatbuffer_size);

        // Push the data
        XrResult result = m_push_fn(m_push_tensor, &tensorData);
        if (result != XR_SUCCESS)
        {
            std::cerr << "Failed to push tensor data, result=" << result << std::endl;
            return false;
        }

        ++m_push_count;
        return true;
    }

    size_t get_push_count() const
    {
        return m_push_count;
    }

    const SchemaPusherConfig& config() const
    {
        return m_config;
    }

private:
    void initialize_push_tensor_functions()
    {
        XrResult result;

        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrCreatePushTensorCollectionNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_fn));
        if (result != XR_SUCCESS || m_create_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrCreatePushTensorCollectionNV function pointer");
        }

        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrPushTensorCollectionDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_push_fn));
        if (result != XR_SUCCESS || m_push_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrPushTensorCollectionDataNV function pointer");
        }

        result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrDestroyPushTensorCollectionNV",
                                                 reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_fn));
        if (result != XR_SUCCESS || m_destroy_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrDestroyPushTensorCollectionNV function pointer");
        }
    }

    void create_tensor_collection()
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
        std::strncpy(
            tensorInfo.properties.identifier, m_config.tensor_identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
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
        std::strncpy(
            createInfo.data.localizedName, m_config.localized_name.c_str(), XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1);
        createInfo.data.localizedName[XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1] = '\0';
        // Zero out UUID (optional, runtime may assign)
        std::memset(&createInfo.data.uuid, 0, sizeof(createInfo.data.uuid));

        // Create the tensor collection
        XrPushTensorCollectionCreateResultNV createResult{};
        createResult.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_RESULT_NV;
        createResult.next = nullptr;

        XrResult result = m_create_fn(m_handles.session, &createInfo, &createResult, &m_push_tensor);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("Failed to create push tensor collection, result=" + std::to_string(result));
        }

        m_tensor_collection_id = createResult.tensorCollectionId;
    }

    OpenXRSessionHandles m_handles;
    SchemaPusherConfig m_config;
    XrTimeConverter m_time_converter;

    // Push tensor collection handle
    XrPushTensorCollectionNV m_push_tensor{ XR_NULL_HANDLE };
    XrTensorCollectionIDNV m_tensor_collection_id{ 0 };

    // Extension function pointers
    PFN_xrCreatePushTensorCollectionNV m_create_fn{ nullptr };
    PFN_xrPushTensorCollectionDataNV m_push_fn{ nullptr };
    PFN_xrDestroyPushTensorCollectionNV m_destroy_fn{ nullptr };

    // Statistics
    size_t m_push_count{ 0 };
};

// =============================================================================
// SchemaPusherBase implementation (delegates to Impl)
// =============================================================================

SchemaPusherBase::SchemaPusherBase(const OpenXRSessionHandles& handles, SchemaPusherConfig config)
    : m_impl(std::make_unique<Impl>(handles, std::move(config)))
{
}

SchemaPusherBase::~SchemaPusherBase() = default;

bool SchemaPusherBase::push_buffer(const uint8_t* buffer, size_t size)
{
    return m_impl->push_buffer(buffer, size);
}

size_t SchemaPusherBase::get_push_count() const
{
    return m_impl->get_push_count();
}

const SchemaPusherConfig& SchemaPusherBase::config() const
{
    return m_impl->config();
}

} // namespace core
