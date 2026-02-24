// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/schema_tracker.hpp"

#include <openxr/openxr.h>
#include <oxr_utils/oxr_funcs.hpp>

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

SchemaTracker::SchemaTracker(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
    : m_handles(handles), m_config(std::move(config)), m_time_converter(handles)
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

SchemaTracker::~SchemaTracker()
{
    // m_tensor_list is guaranteed to be non-null by create_tensor_list(), or the constructor would have thrown.
    assert(m_tensor_list != XR_NULL_HANDLE && m_destroy_list_fn != nullptr);

    XrResult result = m_destroy_list_fn(m_tensor_list);
    if (result != XR_SUCCESS)
    {
        std::cerr << "Warning: Failed to destroy tensor list, result=" << result << std::endl;
    }
}

std::vector<std::string> SchemaTracker::get_required_extensions()
{
    std::vector<std::string> exts = { "XR_NVX1_tensor_data" };
    for (const auto& ext : XrTimeConverter::get_required_extensions())
    {
        exts.push_back(ext);
    }
    return exts;
}

bool SchemaTracker::read_sample(SampleResult& out)
{
    // Try to discover target collection if not found yet (or if it was lost)
    if (!m_target_collection_index)
    {
        // Poll for tensor list updates only when we need to discover
        poll_for_updates();

        m_target_collection_index = find_target_collection();
        if (!m_target_collection_index)
        {
            return false; // Collection not available yet
        }
        std::cout << "Found target collection at index " << *m_target_collection_index << std::endl;
    }

    // Try to read next sample
    return read_next_sample(out);
}

const SchemaTrackerConfig& SchemaTracker::config() const
{
    return m_config;
}

void SchemaTracker::initialize_tensor_data_functions()
{
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrGetTensorListLatestGenerationNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_get_latest_gen_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrCreateTensorListNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_create_list_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrGetTensorListPropertiesNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_get_list_props_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrGetTensorCollectionPropertiesNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_get_coll_props_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrGetTensorDataNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_get_data_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrUpdateTensorListNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_update_list_fn));
    loadExtensionFunction(m_handles.instance, m_handles.xrGetInstanceProcAddr, "xrDestroyTensorListNV",
                          reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_list_fn));
}

void SchemaTracker::create_tensor_list()
{
    XrCreateTensorListInfoNV createInfo{ XR_TYPE_CREATE_TENSOR_LIST_INFO_NV };
    createInfo.next = nullptr;

    XrResult result = m_create_list_fn(m_handles.session, &createInfo, &m_tensor_list);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("Failed to create tensor list, result=" + std::to_string(result));
    }
}

void SchemaTracker::poll_for_updates()
{
    // Check if tensor list needs update
    uint64_t latest_generation = 0;
    XrResult result = m_get_latest_gen_fn(m_handles.session, &latest_generation);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("Failed to get latest generation, result=" + std::to_string(result));
    }

    if (latest_generation != m_cached_generation)
    {
        result = m_update_list_fn(m_tensor_list);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("Failed to update tensor list, result=" + std::to_string(result));
        }
        m_cached_generation = latest_generation;
        // Re-discover collections after update
        m_target_collection_index = find_target_collection();
    }
}

std::optional<uint32_t> SchemaTracker::find_target_collection()
{
    // Get list properties
    XrSystemTensorListPropertiesNV listProps{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };

    XrResult result = m_get_list_props_fn(m_tensor_list, &listProps);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("Failed to get list properties, result=" + std::to_string(result));
    }

    if (listProps.tensorCollectionCount == 0)
    {
        return std::nullopt; // No collections available yet
    }

    // Search for matching collection
    for (uint32_t i = 0; i < listProps.tensorCollectionCount; ++i)
    {
        XrTensorCollectionPropertiesNV collProps{ XR_TYPE_TENSOR_COLLECTION_PROPERTIES_NV };

        result = m_get_coll_props_fn(m_tensor_list, i, &collProps);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("Failed to get collection properties, result=" + std::to_string(result));
        }

        if (std::strncmp(collProps.data.identifier, m_config.collection_id.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE) == 0)
        {
            // Found matching collection
            m_sample_batch_stride = collProps.sampleBatchStride;
            m_sample_size = collProps.data.totalSampleSize;
            return i;
        }
    }

    return std::nullopt;
}

bool SchemaTracker::read_next_sample(SampleResult& out)
{
    if (!m_target_collection_index.has_value())
    {
        return false;
    }

    // Prepare retrieval info
    XrTensorDataRetrievalInfoNV retrievalInfo{ XR_TYPE_TENSOR_DATA_RETRIEVAL_INFO_NV };
    retrievalInfo.next = nullptr;
    retrievalInfo.tensorCollectionIndex = m_target_collection_index.value();
    retrievalInfo.startSampleIndex = m_last_sample_index.has_value() ? m_last_sample_index.value() + 1 : 0;

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
        // TODO: Check against XR_ERROR_TENSOR_LOST_NV when it's reported by the runtime.
        // if (result == XR_ERROR_TENSOR_LOST_NV)
        // {
        //     m_target_collection_index = std::nullopt;
        //     return false;
        // }
        std::cerr << "Failed to get tensor data, result=" << result << std::endl;
        m_target_collection_index = std::nullopt;
        return false;
    }

    if (tensorData.writtenSampleCount == 0)
    {
        return false; // No new samples
    }

    // Update last sample index
    if (!m_last_sample_index.has_value() || metadata.sampleIndex > m_last_sample_index.value())
    {
        m_last_sample_index = metadata.sampleIndex;
    }

    // Guard against invalid runtime state: batch stride must cover at least one full sample.
    if (dataBuffer.size() < m_sample_size)
    {
        std::cerr << "[SchemaTracker] read_next_sample: dataBuffer (" << dataBuffer.size()
                  << " B) is smaller than m_sample_size (" << m_sample_size << " B); skipping copy." << std::endl;
        return false;
    }

    // Copy data to output buffer (trim to sample size, not batch stride)
    out.buffer.resize(m_sample_size);
    std::memcpy(out.buffer.data(), dataBuffer.data(), m_sample_size);

    // Convert XrTime values from tensor metadata back to monotonic nanoseconds.
    // The pusher stored monotonic ns converted to XrTime; we invert that here so
    // DeviceDataTimestamp always carries monotonic nanoseconds in the _local_common_clock_ fields.
    int64_t available_ns =
        m_time_converter.convert_xrtime_to_monotonic_ns(static_cast<XrTime>(metadata.arrivalTimestamp));
    int64_t sample_ns = m_time_converter.convert_xrtime_to_monotonic_ns(static_cast<XrTime>(metadata.timestamp));

    out.timestamp = DeviceDataTimestamp(available_ns, // available_time_local_common_clock
                                        sample_ns, // sample_time_local_common_clock
                                        static_cast<int64_t>(metadata.rawDeviceTimestamp) // sample_time_raw_device_clock
    );

    return true;
}

} // namespace core
