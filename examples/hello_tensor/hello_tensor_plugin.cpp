// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "hello_tensor_plugin.hpp"

#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace plugins
{
namespace hello_tensor
{

// DLPack dtype code for float32: code=2 (float), bits=32
// Formula: (code << 8) | bits
static constexpr uint32_t DLPACK_DTYPE_FLOAT32 = (2 << 8) | 32;

HelloTensorPlugin::HelloTensorPlugin(const std::string& plugin_root_id) : m_root_id(plugin_root_id)
{
    std::cout << "Initializing HelloTensorPlugin with root: " << m_root_id << std::endl;

    // Create OpenXR session with push tensor extension
    std::vector<std::string> extensions = { XR_NVX1_PUSH_TENSOR_EXTENSION_NAME, XR_NVX1_TENSOR_DATA_EXTENSION_NAME };

    m_session = core::OpenXRSession::Create("HelloTensor", extensions);
    if (!m_session)
    {
        throw std::runtime_error("Failed to create OpenXR session");
    }

    // Initialize extension functions
    initialize_push_tensor_functions();

    // Create the tensor collection
    create_tensor_collection();

    // Start worker thread
    m_running = true;
    m_thread = std::thread(&HelloTensorPlugin::worker_thread, this);

    std::cout << "HelloTensorPlugin initialized and running" << std::endl;
}

HelloTensorPlugin::~HelloTensorPlugin()
{
    std::cout << "Shutting down HelloTensorPlugin..." << std::endl;

    // Stop worker thread
    m_running = false;
    if (m_thread.joinable())
    {
        m_thread.join();
    }

    // Destroy the push tensor collection
    if (m_push_tensor != XR_NULL_HANDLE && m_destroy_fn != nullptr)
    {
        XrResult result = m_destroy_fn(m_push_tensor);
        if (result != XR_SUCCESS)
        {
            std::cerr << "Warning: Failed to destroy push tensor collection, result=" << result << std::endl;
        }
        else
        {
            std::cout << "Push tensor collection destroyed" << std::endl;
        }
    }

    std::cout << "HelloTensorPlugin shutdown complete" << std::endl;
}

void HelloTensorPlugin::initialize_push_tensor_functions()
{
    const auto handles = m_session->get_handles();

    // Get function pointers for push tensor extension
    XrResult result;

    result = xrGetInstanceProcAddr(
        handles.instance, "xrCreatePushTensorCollectionNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_fn));
    if (result != XR_SUCCESS || m_create_fn == nullptr)
    {
        throw std::runtime_error("Failed to get xrCreatePushTensorCollectionNV function pointer");
    }

    result = xrGetInstanceProcAddr(
        handles.instance, "xrPushTensorCollectionDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_push_fn));
    if (result != XR_SUCCESS || m_push_fn == nullptr)
    {
        throw std::runtime_error("Failed to get xrPushTensorCollectionDataNV function pointer");
    }

    result = xrGetInstanceProcAddr(
        handles.instance, "xrDestroyPushTensorCollectionNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_fn));
    if (result != XR_SUCCESS || m_destroy_fn == nullptr)
    {
        throw std::runtime_error("Failed to get xrDestroyPushTensorCollectionNV function pointer");
    }

    std::cout << "Push tensor extension functions loaded successfully" << std::endl;
}

void HelloTensorPlugin::create_tensor_collection()
{
    const auto handles = m_session->get_handles();

    // Set up DLPack tensor properties for a 4x4 float32 matrix
    XrPushTensorDlpackCreateInfoNV dlpackInfo{};
    dlpackInfo.type = XR_TYPE_PUSH_TENSOR_DLPACK_CREATE_INFO_NV;
    dlpackInfo.next = nullptr;
    dlpackInfo.data.versionMajor = 1;
    dlpackInfo.data.versionMinor = 0;
    dlpackInfo.data.dtype = DLPACK_DTYPE_FLOAT32;
    dlpackInfo.data.ndim = 2;
    dlpackInfo.data.shape[0] = TENSOR_ROWS;
    dlpackInfo.data.shape[1] = TENSOR_COLS;
    // Strides are in bytes: row stride = TENSOR_COLS * sizeof(float), col stride = sizeof(float)
    dlpackInfo.data.strides[0] = TENSOR_COLS * sizeof(float);
    dlpackInfo.data.strides[1] = sizeof(float);
    dlpackInfo.data.byte_offset = 0;

    // Create tensor info with DLPack properties chained
    XrPushTensorCreateInfoNV tensorInfo{};
    tensorInfo.type = XR_TYPE_PUSH_TENSOR_CREATE_INFO_NV;
    tensorInfo.next = &dlpackInfo;
    tensorInfo.properties.dataType = XR_TENSOR_DATA_TYPE_DLPACK_NV;
    tensorInfo.properties.dataTypeSize = TENSOR_SIZE * sizeof(float);
    tensorInfo.properties.offset = 0;
    std::strncpy(tensorInfo.properties.identifier, "hello_matrix", XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
    tensorInfo.properties.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';

    // Create tensor collection with one tensor
    XrPushTensorCollectionCreateInfoNV createInfo{};
    createInfo.type = XR_TYPE_PUSH_TENSOR_COLLECTION_CREATE_INFO_NV;
    createInfo.next = nullptr;
    createInfo.tensors = &tensorInfo;
    createInfo.data.tensorCount = 1;
    createInfo.data.totalSampleSize = TENSOR_SIZE * sizeof(float);
    std::strncpy(createInfo.data.identifier, m_root_id.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE - 1);
    createInfo.data.identifier[XR_MAX_TENSOR_IDENTIFIER_SIZE - 1] = '\0';
    std::strncpy(createInfo.data.localizedName, "Hello Tensor Demo", XR_MAX_TENSOR_LOCALIZED_NAME_SIZE - 1);
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

    m_tensor_collection_id = createResult.tensorCollectionId;
    std::cout << "Push tensor collection created successfully" << std::endl;
    std::cout << "  Tensor Collection ID: " << m_tensor_collection_id << std::endl;
    std::cout << "  Identifier: " << m_root_id << std::endl;
    std::cout << "  Shape: [" << TENSOR_ROWS << ", " << TENSOR_COLS << "]" << std::endl;
    std::cout << "  Data Type: DLPack float32" << std::endl;
}

void HelloTensorPlugin::push_sample(int sample_count)
{
    // Create sample data: 4x4 matrix with incrementing values
    // Each sample has unique values based on sample_count
    float data[TENSOR_SIZE];
    for (int i = 0; i < TENSOR_SIZE; ++i)
    {
        // Generate values: sample_count * 16 + element_index
        data[i] = static_cast<float>(sample_count * TENSOR_SIZE + i);
    }

    // Get current time for timestamps
    auto now = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
    XrTime xr_time = static_cast<XrTime>(ns);

    // Prepare push data structure
    XrPushTensorCollectionDataNV tensorData{};
    tensorData.type = XR_TYPE_PUSH_TENSOR_COLLECTION_DATA_NV;
    tensorData.next = nullptr;
    tensorData.timestamp = xr_time;
    tensorData.rawDeviceTimestamp = static_cast<uint64_t>(ns);
    tensorData.buffer = reinterpret_cast<const uint8_t*>(data);
    tensorData.bufferSize = sizeof(data);

    // Push the data
    XrResult result = m_push_fn(m_push_tensor, &tensorData);
    if (result != XR_SUCCESS)
    {
        std::cerr << "Failed to push tensor data, result=" << result << std::endl;
        return;
    }

    // Print sample info (first and last values for verification)
    std::cout << "Pushed sample " << sample_count << " [" << std::fixed << std::setprecision(1) << data[0] << " ... "
              << data[TENSOR_SIZE - 1] << "]" << std::endl;
}

void HelloTensorPlugin::worker_thread()
{
    std::cout << "Worker thread started, pushing samples every 50ms..." << std::endl;

    int sample_count = 0;
    constexpr int MAX_SAMPLES = 100;

    while (m_running && sample_count < MAX_SAMPLES)
    {
        push_sample(sample_count);
        sample_count++;

        // Sleep for 50ms between samples
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    std::cout << "Worker thread stopped after " << sample_count << " samples" << std::endl;
    m_running = false;
}

} // namespace hello_tensor
} // namespace plugins
