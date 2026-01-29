// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/tensorio/tensor_reader.hpp"

#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{
namespace tensorio
{

std::unique_ptr<TensorReader> TensorReader::create(const OpenXRSessionHandles& handles)
{
    return std::unique_ptr<TensorReader>(new TensorReader(handles));
}

TensorReader::TensorReader(const OpenXRSessionHandles& handles) : m_handles(handles)
{
    initialize_extension_functions();
    create_tensor_list();
}

TensorReader::~TensorReader()
{
    if (m_tensor_list != XR_NULL_HANDLE && m_destroy_list_fn != nullptr)
    {
        XrResult result = m_destroy_list_fn(m_tensor_list);
        if (result != XR_SUCCESS)
        {
            std::cerr << "TensorReader: Warning: Failed to destroy tensor list, result=" << result << std::endl;
        }
    }
}

void TensorReader::initialize_extension_functions()
{
    if (m_handles.xrGetInstanceProcAddr == nullptr)
    {
        throw std::runtime_error("TensorReader: xrGetInstanceProcAddr is null");
    }

    XrResult result;

    result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrGetTensorListLatestGenerationNV",
                                             reinterpret_cast<PFN_xrVoidFunction*>(&m_get_latest_gen_fn));
    if (result != XR_SUCCESS || m_get_latest_gen_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrGetTensorListLatestGenerationNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrCreateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_list_fn));
    if (result != XR_SUCCESS || m_create_list_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrCreateTensorListNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrGetTensorListPropertiesNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_list_props_fn));
    if (result != XR_SUCCESS || m_get_list_props_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrGetTensorListPropertiesNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(m_handles.instance, "xrGetTensorCollectionPropertiesNV",
                                             reinterpret_cast<PFN_xrVoidFunction*>(&m_get_coll_props_fn));
    if (result != XR_SUCCESS || m_get_coll_props_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrGetTensorCollectionPropertiesNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrGetTensorPropertiesNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_tensor_props_fn));
    if (result != XR_SUCCESS || m_get_tensor_props_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrGetTensorPropertiesNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrGetTensorDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_data_fn));
    if (result != XR_SUCCESS || m_get_data_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrGetTensorDataNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrUpdateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_update_list_fn));
    if (result != XR_SUCCESS || m_update_list_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrUpdateTensorListNV function pointer");
    }

    result = m_handles.xrGetInstanceProcAddr(
        m_handles.instance, "xrDestroyTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_list_fn));
    if (result != XR_SUCCESS || m_destroy_list_fn == nullptr)
    {
        throw std::runtime_error("TensorReader: Failed to get xrDestroyTensorListNV function pointer");
    }
}

void TensorReader::create_tensor_list()
{
    XrCreateTensorListInfoNV create_info{ XR_TYPE_CREATE_TENSOR_LIST_INFO_NV };
    create_info.next = nullptr;

    XrResult result = m_create_list_fn(m_handles.session, &create_info, &m_tensor_list);
    if (result != XR_SUCCESS)
    {
        throw std::runtime_error("TensorReader: Failed to create tensor list, result=" + std::to_string(result));
    }

    // Get initial generation number
    XrSystemTensorListPropertiesNV list_props{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };
    list_props.next = nullptr;
    result = m_get_list_props_fn(m_tensor_list, &list_props);
    if (result == XR_SUCCESS)
    {
        m_cached_generation = list_props.generationNumber;
    }
}

bool TensorReader::update_list_if_needed()
{
    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return false;
    }

    uint64_t latest_generation = 0;
    XrResult result = m_get_latest_gen_fn(m_handles.session, &latest_generation);
    if (result != XR_SUCCESS)
    {
        return false;
    }

    if (latest_generation != m_cached_generation)
    {
        result = m_update_list_fn(m_tensor_list);
        if (result == XR_SUCCESS)
        {
            m_cached_generation = latest_generation;
            return true;
        }
    }

    return false;
}

bool TensorReader::update_list()
{
    if (m_tensor_list == XR_NULL_HANDLE || m_update_list_fn == nullptr)
    {
        return false;
    }

    XrResult result = m_update_list_fn(m_tensor_list);
    if (result != XR_SUCCESS)
    {
        return false;
    }

    // Update cached generation
    XrSystemTensorListPropertiesNV list_props{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };
    list_props.next = nullptr;
    result = m_get_list_props_fn(m_tensor_list, &list_props);
    if (result == XR_SUCCESS)
    {
        m_cached_generation = list_props.generationNumber;
    }

    return true;
}

uint32_t TensorReader::get_collection_count() const
{
    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return 0;
    }

    XrSystemTensorListPropertiesNV list_props{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };
    list_props.next = nullptr;

    XrResult result = m_get_list_props_fn(m_tensor_list, &list_props);
    if (result != XR_SUCCESS)
    {
        return 0;
    }

    return list_props.tensorCollectionCount;
}

int TensorReader::find_collection(const std::string& identifier) const
{
    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return -1;
    }

    uint32_t count = get_collection_count();
    for (uint32_t i = 0; i < count; ++i)
    {
        XrTensorCollectionPropertiesNV coll_props{ XR_TYPE_TENSOR_COLLECTION_PROPERTIES_NV };
        coll_props.next = nullptr;

        XrResult result = m_get_coll_props_fn(m_tensor_list, i, &coll_props);
        if (result != XR_SUCCESS)
        {
            continue;
        }

        if (std::strncmp(coll_props.data.identifier, identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE) == 0)
        {
            return static_cast<int>(i);
        }
    }

    return -1;
}

std::optional<TensorCollectionInfo> TensorReader::get_collection_info(uint32_t index) const
{
    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return std::nullopt;
    }

    XrTensorCollectionPropertiesNV coll_props{ XR_TYPE_TENSOR_COLLECTION_PROPERTIES_NV };
    coll_props.next = nullptr;

    XrResult result = m_get_coll_props_fn(m_tensor_list, index, &coll_props);
    if (result != XR_SUCCESS)
    {
        return std::nullopt;
    }

    TensorCollectionInfo info;
    info.collection_id = coll_props.tensorCollectionId;
    info.identifier = coll_props.data.identifier;
    info.localized_name = coll_props.data.localizedName;
    info.tensor_count = coll_props.data.tensorCount;
    info.total_sample_size = coll_props.data.totalSampleSize;
    info.sample_batch_stride = coll_props.sampleBatchStride;

    return info;
}

std::optional<TensorInfo> TensorReader::get_tensor_info(uint32_t collection_index, uint32_t tensor_index) const
{
    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return std::nullopt;
    }

    // Chain DLPack properties to get full info
    XrTensorDlpackPropertiesNV dlpack_props{ XR_TYPE_TENSOR_DLPACK_PROPERTIES_NV };
    dlpack_props.next = nullptr;

    XrTensorPropertiesNV tensor_props{ XR_TYPE_TENSOR_PROPERTIES_NV };
    tensor_props.next = &dlpack_props;

    XrResult result = m_get_tensor_props_fn(m_tensor_list, collection_index, tensor_index, &tensor_props);
    if (result != XR_SUCCESS)
    {
        return std::nullopt;
    }

    TensorInfo info;
    info.identifier = tensor_props.data.identifier;
    info.data_type = tensor_props.data.dataType;
    info.data_type_size = tensor_props.data.dataTypeSize;
    info.offset = tensor_props.data.offset;

    // If this is a DLPack tensor, extract the properties
    if (tensor_props.data.dataType == XR_TENSOR_DATA_TYPE_DLPACK_NV)
    {
        DlpackInfo dlpack;
        dlpack.version_major = dlpack_props.data.versionMajor;
        dlpack.version_minor = dlpack_props.data.versionMinor;
        dlpack.dtype = dlpack_props.data.dtype;
        dlpack.ndim = dlpack_props.data.ndim;
        dlpack.byte_offset = dlpack_props.data.byte_offset;

        for (int32_t d = 0; d < dlpack_props.data.ndim && d < XR_MAX_TENSOR_DLPACK_DIMENSIONS; ++d)
        {
            dlpack.shape[d] = dlpack_props.data.shape[d];
            dlpack.strides[d] = dlpack_props.data.strides[d];
        }

        info.dlpack_info = dlpack;
    }

    return info;
}

std::vector<Sample> TensorReader::read_samples(uint32_t collection_index,
                                               int64_t start_sample_index,
                                               uint32_t max_samples) const
{
    std::vector<Sample> samples;

    if (m_tensor_list == XR_NULL_HANDLE)
    {
        return samples;
    }

    // Get collection info for stride
    auto coll_info = get_collection_info(collection_index);
    if (!coll_info.has_value())
    {
        return samples;
    }

    uint32_t sample_batch_stride = coll_info->sample_batch_stride;
    if (sample_batch_stride == 0)
    {
        sample_batch_stride = coll_info->total_sample_size;
    }

    // Prepare retrieval info
    XrTensorDataRetrievalInfoNV retrieval_info{ XR_TYPE_TENSOR_DATA_RETRIEVAL_INFO_NV };
    retrieval_info.next = nullptr;
    retrieval_info.tensorCollectionIndex = collection_index;
    retrieval_info.startSampleIndex = start_sample_index;

    // Prepare output buffers
    std::vector<XrTensorSampleMetadataNV> metadata(max_samples);
    std::vector<uint8_t> data_buffer(max_samples * sample_batch_stride);

    XrTensorDataNV tensor_data{ XR_TYPE_TENSOR_DATA_NV };
    tensor_data.next = nullptr;
    tensor_data.metadataArray = metadata.data();
    tensor_data.metadataCapacity = max_samples;
    tensor_data.buffer = data_buffer.data();
    tensor_data.bufferCapacity = static_cast<uint32_t>(data_buffer.size());
    tensor_data.writtenSampleCount = 0;

    XrResult result = m_get_data_fn(m_tensor_list, &retrieval_info, &tensor_data);
    if (result != XR_SUCCESS)
    {
        if (result == XR_ERROR_TENSOR_LOST_NV)
        {
            std::cerr << "TensorReader: Tensor collection lost" << std::endl;
        }
        return samples;
    }

    // Convert to Sample structs
    samples.reserve(tensor_data.writtenSampleCount);
    for (uint32_t s = 0; s < tensor_data.writtenSampleCount; ++s)
    {
        Sample sample;
        sample.sample_index = metadata[s].sampleIndex;
        sample.timestamp = metadata[s].timestamp;
        sample.raw_device_timestamp = metadata[s].rawDeviceTimestamp;
        sample.arrival_timestamp = metadata[s].arrivalTimestamp;

        // Copy sample data
        const uint8_t* sample_start = data_buffer.data() + s * sample_batch_stride;
        sample.data.assign(sample_start, sample_start + coll_info->total_sample_size);

        samples.push_back(std::move(sample));
    }

    return samples;
}

} // namespace tensorio
} // namespace core
