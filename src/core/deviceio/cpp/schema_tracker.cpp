// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/schema_tracker.hpp"

#include <openxr/openxr.h>

#include <XR_NVX1_tensor_data.h>
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

// =============================================================================
// SchemaTracker Implementation
// =============================================================================

SchemaTracker::SchemaTracker(SchemaTrackerConfig config) : m_config(std::move(config))
{
}

std::vector<std::string> SchemaTracker::get_required_extensions() const
{
    return { REQUIRED_EXTENSIONS[0] };
}

const SchemaTrackerConfig& SchemaTracker::get_config() const
{
    return m_config;
}

// =============================================================================
// SchemaTracker::Impl::ImplData - Internal data for tensor reading
// =============================================================================

/*!
 * @brief Internal data for SchemaTracker::Impl.
 *
 * Uses externally-provided OpenXR session handles for tensor read operations.
 */
class SchemaTracker::Impl::ImplData
{
public:
    ImplData(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
        : m_handles(handles), m_config(std::move(config))
    {
        // Validate handles
        assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
        assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
        assert(handles.xrGetInstanceProcAddr && "xrGetInstanceProcAddr cannot be null");

        // Initialize extension functions using the provided xrGetInstanceProcAddr
        initialize_tensor_data_functions();

        // Create tensor list
        create_tensor_list();

        std::cout << "SchemaTracker initialized, looking for collection: " << m_config.collection_id << std::endl;
    }

    ~ImplData()
    {
        // Destroy tensor list
        if (m_tensor_list != XR_NULL_HANDLE && m_destroy_list_fn != nullptr)
        {
            XrResult result = m_destroy_list_fn(m_tensor_list);
            if (result != XR_SUCCESS)
            {
                std::cerr << "Warning: Failed to destroy tensor list, result=" << result << std::endl;
            }
        }
    }

    bool is_connected() const
    {
        return m_target_collection_index >= 0;
    }

    size_t get_read_count() const
    {
        return m_read_count;
    }

    bool read_buffer(std::vector<uint8_t>& buffer)
    {
        // Poll for tensor list updates
        poll_for_updates();

        // Try to discover target collection if not found yet
        if (m_target_collection_index < 0)
        {
            m_target_collection_index = find_target_collection();
            if (m_target_collection_index < 0)
            {
                return false; // Collection not available yet
            }
            std::cout << "Found target collection at index " << m_target_collection_index << std::endl;
        }

        // Try to read next sample
        return read_next_sample(buffer);
    }

    const SchemaTrackerConfig& config() const
    {
        return m_config;
    }

private:
    void initialize_tensor_data_functions()
    {
        XrResult result;

        // xrGetTensorListLatestGenerationNV
        result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrGetTensorListLatestGenerationNV",
                                                 reinterpret_cast<PFN_xrVoidFunction*>(&m_get_latest_gen_fn));
        if (result != XR_SUCCESS || m_get_latest_gen_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorListLatestGenerationNV function pointer");
        }

        // xrCreateTensorListNV
        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrCreateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_list_fn));
        if (result != XR_SUCCESS || m_create_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrCreateTensorListNV function pointer");
        }

        // xrGetTensorListPropertiesNV
        result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrGetTensorListPropertiesNV",
                                                 reinterpret_cast<PFN_xrVoidFunction*>(&m_get_list_props_fn));
        if (result != XR_SUCCESS || m_get_list_props_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorListPropertiesNV function pointer");
        }

        // xrGetTensorCollectionPropertiesNV
        result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrGetTensorCollectionPropertiesNV",
                                                 reinterpret_cast<PFN_xrVoidFunction*>(&m_get_coll_props_fn));
        if (result != XR_SUCCESS || m_get_coll_props_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorCollectionPropertiesNV function pointer");
        }

        // xrGetTensorDataNV
        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrGetTensorDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_data_fn));
        if (result != XR_SUCCESS || m_get_data_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorDataNV function pointer");
        }

        // xrUpdateTensorListNV
        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrUpdateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_update_list_fn));
        if (result != XR_SUCCESS || m_update_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrUpdateTensorListNV function pointer");
        }

        // xrDestroyTensorListNV
        result = m_handles.xrGetInstanceProcAddr(
            m_handles.instance, "xrDestroyTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_list_fn));
        if (result != XR_SUCCESS || m_destroy_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrDestroyTensorListNV function pointer");
        }
    }

    void create_tensor_list()
    {
        XrCreateTensorListInfoNV createInfo{ XR_TYPE_CREATE_TENSOR_LIST_INFO_NV };
        createInfo.next = nullptr;

        XrResult result = m_create_list_fn(m_handles.session, &createInfo, &m_tensor_list);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("Failed to create tensor list, result=" + std::to_string(result));
        }
    }

    void poll_for_updates()
    {
        // Check if tensor list needs update
        uint64_t latest_generation = 0;
        XrResult result = m_get_latest_gen_fn(m_handles.session, &latest_generation);
        if (result == XR_SUCCESS && latest_generation != m_cached_generation)
        {
            result = m_update_list_fn(m_tensor_list);
            if (result == XR_SUCCESS)
            {
                m_cached_generation = latest_generation;
                // Re-discover collections after update
                m_target_collection_index = find_target_collection();
            }
        }
    }

    int find_target_collection()
    {
        // Get list properties
        XrSystemTensorListPropertiesNV listProps{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };
        listProps.next = nullptr;

        XrResult result = m_get_list_props_fn(m_tensor_list, &listProps);
        if (result != XR_SUCCESS)
        {
            return -1;
        }

        if (listProps.tensorCollectionCount == 0)
        {
            return -1; // No collections available yet
        }

        // Search for matching collection
        for (uint32_t i = 0; i < listProps.tensorCollectionCount; ++i)
        {
            XrTensorCollectionPropertiesNV collProps{ XR_TYPE_TENSOR_COLLECTION_PROPERTIES_NV };
            collProps.next = nullptr;

            result = m_get_coll_props_fn(m_tensor_list, i, &collProps);
            if (result != XR_SUCCESS)
            {
                continue;
            }

            if (std::strncmp(collProps.data.identifier, m_config.collection_id.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE) ==
                0)
            {
                // Found matching collection
                m_sample_batch_stride = collProps.sampleBatchStride;
                m_sample_size = collProps.data.totalSampleSize;
                return static_cast<int>(i);
            }
        }

        return -1;
    }

    bool read_next_sample(std::vector<uint8_t>& buffer)
    {
        if (m_target_collection_index < 0)
        {
            return false;
        }

        // Prepare retrieval info
        XrTensorDataRetrievalInfoNV retrievalInfo{ XR_TYPE_TENSOR_DATA_RETRIEVAL_INFO_NV };
        retrievalInfo.next = nullptr;
        retrievalInfo.tensorCollectionIndex = static_cast<uint32_t>(m_target_collection_index);
        retrievalInfo.startSampleIndex = m_last_sample_index + 1;

        // Prepare output buffers (read one sample at a time for simplicity)
        XrTensorSampleMetadataNV metadata{};
        std::vector<uint8_t> dataBuffer(m_sample_batch_stride);

        XrTensorDataNV tensorData{ XR_TYPE_TENSOR_DATA_NV };
        tensorData.next = nullptr;
        tensorData.metadataArray = &metadata;
        tensorData.metadataCapacity = 1;
        tensorData.buffer = dataBuffer.data();
        tensorData.bufferCapacity = static_cast<uint32_t>(dataBuffer.size());
        tensorData.writtenSampleCount = 0;

        // Retrieve samples
        XrResult result = m_get_data_fn(m_tensor_list, &retrievalInfo, &tensorData);
        if (result != XR_SUCCESS)
        {
            if (result == XR_ERROR_TENSOR_LOST_NV)
            {
                std::cerr << "Tensor collection lost, will re-discover..." << std::endl;
                m_target_collection_index = -1;
            }
            return false;
        }

        if (tensorData.writtenSampleCount == 0)
        {
            return false; // No new samples
        }

        // Update last sample index
        if (metadata.sampleIndex > m_last_sample_index)
        {
            m_last_sample_index = metadata.sampleIndex;
        }

        // Copy data to output buffer (trim to sample size, not batch stride)
        buffer.resize(m_sample_size);
        std::memcpy(buffer.data(), dataBuffer.data(), m_sample_size);

        ++m_read_count;
        return true;
    }

    OpenXRSessionHandles m_handles;
    SchemaTrackerConfig m_config;

    // Tensor list handle
    XrTensorListNV m_tensor_list{ XR_NULL_HANDLE };

    // Extension function pointers
    PFN_xrGetTensorListLatestGenerationNV m_get_latest_gen_fn{ nullptr };
    PFN_xrCreateTensorListNV m_create_list_fn{ nullptr };
    PFN_xrGetTensorListPropertiesNV m_get_list_props_fn{ nullptr };
    PFN_xrGetTensorCollectionPropertiesNV m_get_coll_props_fn{ nullptr };
    PFN_xrGetTensorDataNV m_get_data_fn{ nullptr };
    PFN_xrUpdateTensorListNV m_update_list_fn{ nullptr };
    PFN_xrDestroyTensorListNV m_destroy_list_fn{ nullptr };

    // Target collection info
    int m_target_collection_index{ -1 };
    uint32_t m_sample_batch_stride{ 0 };
    uint32_t m_sample_size{ 0 };

    // Generation tracking
    uint64_t m_cached_generation{ 0 };

    // Sample tracking
    int64_t m_last_sample_index{ -1 };

    // Statistics
    size_t m_read_count{ 0 };
};

// =============================================================================
// SchemaTracker::Impl Implementation (delegates to ImplData)
// =============================================================================

SchemaTracker::Impl::Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
    : m_data(std::make_unique<ImplData>(handles, std::move(config)))
{
}

SchemaTracker::Impl::~Impl() = default;

bool SchemaTracker::Impl::is_connected() const
{
    return m_data->is_connected();
}

size_t SchemaTracker::Impl::get_read_count() const
{
    return m_data->get_read_count();
}

bool SchemaTracker::Impl::read_buffer(std::vector<uint8_t>& buffer)
{
    return m_data->read_buffer(buffer);
}

const SchemaTrackerConfig& SchemaTracker::Impl::config() const
{
    return m_data->config();
}

} // namespace core
