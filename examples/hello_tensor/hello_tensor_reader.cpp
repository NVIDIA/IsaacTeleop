// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file hello_tensor_reader.cpp
 * @brief Standalone application that reads tensor data from the OpenXR runtime.
 *
 * This application creates an OpenXR session, discovers available tensor collections,
 * and reads tensor samples pushed by hello_tensor (the pusher).
 */

#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>

#include <XR_NVX1_tensor_data.h>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <thread>
#include <vector>

static_assert(ATOMIC_BOOL_LOCK_FREE, "lock-free atomic bool is required for signal safety");

// Use atomic<bool> with relaxed ordering for signal safety
std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

// Maximum number of samples to retrieve in one batch
static constexpr uint32_t MAX_SAMPLES_PER_BATCH = 16;

// Maximum total samples to receive before exiting
static constexpr int MAX_SAMPLES = 100;

// Expected tensor dimensions (4x4 float32 matrix, matching the pusher)
static constexpr int TENSOR_ROWS = 4;
static constexpr int TENSOR_COLS = 4;
static constexpr int TENSOR_SIZE = TENSOR_ROWS * TENSOR_COLS;

class HelloTensorReader
{
public:
    explicit HelloTensorReader(const std::string& target_identifier) : m_target_identifier(target_identifier)
    {
        std::cout << "Initializing HelloTensorReader, looking for: " << m_target_identifier << std::endl;

        // Create OpenXR session with tensor data extension
        std::vector<std::string> extensions = { XR_NVX1_TENSOR_DATA_EXTENSION_NAME };

        m_session = core::OpenXRSession::Create("HelloTensorReader", extensions);
        if (!m_session)
        {
            throw std::runtime_error("Failed to create OpenXR session");
        }

        // Initialize extension functions
        initialize_tensor_data_functions();

        // Create tensor list
        create_tensor_list();

        std::cout << "HelloTensorReader initialized successfully" << std::endl;
    }

    ~HelloTensorReader()
    {
        std::cout << "Shutting down HelloTensorReader..." << std::endl;

        // Destroy tensor list
        if (m_tensor_list != XR_NULL_HANDLE && m_destroy_list_fn != nullptr)
        {
            XrResult result = m_destroy_list_fn(m_tensor_list);
            if (result != XR_SUCCESS)
            {
                std::cerr << "Warning: Failed to destroy tensor list, result=" << result << std::endl;
            }
        }

        std::cout << "HelloTensorReader shutdown complete" << std::endl;
    }

    /*!
     * @brief Main loop that polls for tensor data and prints received samples.
     */
    void run()
    {
        std::cout << "Starting read loop..." << std::endl;

        int64_t last_sample_index = -1;
        int samples_received = 0;
        uint64_t cached_generation = 0;

        while (!g_stop_requested.load(std::memory_order_relaxed) && samples_received < MAX_SAMPLES)
        {
            // Check if tensor list needs update
            uint64_t latest_generation = 0;
            XrResult result = m_get_latest_gen_fn(m_session->get_handles().session, &latest_generation);
            if (result == XR_SUCCESS && latest_generation != cached_generation)
            {
                std::cout << "Tensor list generation changed: " << cached_generation << " -> " << latest_generation
                          << std::endl;
                result = m_update_list_fn(m_tensor_list);
                if (result == XR_SUCCESS)
                {
                    cached_generation = latest_generation;
                    // Re-discover collections after update
                    m_target_collection_index = find_target_collection();
                }
            }

            // Find target collection if not found yet
            if (m_target_collection_index < 0)
            {
                m_target_collection_index = find_target_collection();
                if (m_target_collection_index < 0)
                {
                    // Collection not available yet, wait and retry
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    continue;
                }
                std::cout << "Found target collection at index " << m_target_collection_index << std::endl;
            }

            // Try to read new samples
            int new_samples = read_samples(last_sample_index);
            if (new_samples > 0)
            {
                samples_received += new_samples;
            }
            else
            {
                // No new samples, sleep briefly
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
        }

        if (samples_received >= MAX_SAMPLES)
        {
            std::cout << "Read loop finished after " << samples_received << " samples (limit reached)" << std::endl;
        }
        else
        {
            std::cout << "Read loop finished. Total samples received: " << samples_received << std::endl;
        }
    }

private:
    void initialize_tensor_data_functions()
    {
        const auto handles = m_session->get_handles();
        XrResult result;

        // xrGetTensorListLatestGenerationNV
        result = xrGetInstanceProcAddr(handles.instance, "xrGetTensorListLatestGenerationNV",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&m_get_latest_gen_fn));
        if (result != XR_SUCCESS || m_get_latest_gen_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorListLatestGenerationNV function pointer");
        }

        // xrCreateTensorListNV
        result = xrGetInstanceProcAddr(
            handles.instance, "xrCreateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_create_list_fn));
        if (result != XR_SUCCESS || m_create_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrCreateTensorListNV function pointer");
        }

        // xrGetTensorListPropertiesNV
        result = xrGetInstanceProcAddr(handles.instance, "xrGetTensorListPropertiesNV",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&m_get_list_props_fn));
        if (result != XR_SUCCESS || m_get_list_props_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorListPropertiesNV function pointer");
        }

        // xrGetTensorCollectionPropertiesNV
        result = xrGetInstanceProcAddr(handles.instance, "xrGetTensorCollectionPropertiesNV",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&m_get_coll_props_fn));
        if (result != XR_SUCCESS || m_get_coll_props_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorCollectionPropertiesNV function pointer");
        }

        // xrGetTensorPropertiesNV
        result = xrGetInstanceProcAddr(
            handles.instance, "xrGetTensorPropertiesNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_tensor_props_fn));
        if (result != XR_SUCCESS || m_get_tensor_props_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorPropertiesNV function pointer");
        }

        // xrGetTensorDataNV
        result = xrGetInstanceProcAddr(
            handles.instance, "xrGetTensorDataNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_get_data_fn));
        if (result != XR_SUCCESS || m_get_data_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrGetTensorDataNV function pointer");
        }

        // xrUpdateTensorListNV
        result = xrGetInstanceProcAddr(
            handles.instance, "xrUpdateTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_update_list_fn));
        if (result != XR_SUCCESS || m_update_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrUpdateTensorListNV function pointer");
        }

        // xrDestroyTensorListNV
        result = xrGetInstanceProcAddr(
            handles.instance, "xrDestroyTensorListNV", reinterpret_cast<PFN_xrVoidFunction*>(&m_destroy_list_fn));
        if (result != XR_SUCCESS || m_destroy_list_fn == nullptr)
        {
            throw std::runtime_error("Failed to get xrDestroyTensorListNV function pointer");
        }

        std::cout << "Tensor data extension functions loaded successfully" << std::endl;
    }

    void create_tensor_list()
    {
        const auto handles = m_session->get_handles();

        XrCreateTensorListInfoNV createInfo{ XR_TYPE_CREATE_TENSOR_LIST_INFO_NV };
        createInfo.next = nullptr;

        XrResult result = m_create_list_fn(handles.session, &createInfo, &m_tensor_list);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("Failed to create tensor list, result=" + std::to_string(result));
        }

        std::cout << "Tensor list created successfully" << std::endl;
    }

    /*!
     * @brief Finds the tensor collection matching the target identifier.
     * @return The collection index if found, -1 otherwise.
     */
    int find_target_collection()
    {
        // Get list properties
        XrSystemTensorListPropertiesNV listProps{ XR_TYPE_SYSTEM_TENSOR_LIST_PROPERTIES_NV };
        listProps.next = nullptr;

        XrResult result = m_get_list_props_fn(m_tensor_list, &listProps);
        if (result != XR_SUCCESS)
        {
            std::cerr << "Failed to get tensor list properties, result=" << result << std::endl;
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

            if (std::strncmp(collProps.data.identifier, m_target_identifier.c_str(), XR_MAX_TENSOR_IDENTIFIER_SIZE) == 0)
            {
                // Found matching collection
                std::cout << "Found tensor collection:" << std::endl;
                std::cout << "  Index: " << i << std::endl;
                std::cout << "  Identifier: " << collProps.data.identifier << std::endl;
                std::cout << "  Localized Name: " << collProps.data.localizedName << std::endl;
                std::cout << "  Tensor Count: " << collProps.data.tensorCount << std::endl;
                std::cout << "  Sample Size: " << collProps.data.totalSampleSize << " bytes" << std::endl;
                std::cout << "  Batch Stride: " << collProps.sampleBatchStride << " bytes" << std::endl;

                m_sample_batch_stride = collProps.sampleBatchStride;
                m_sample_size = collProps.data.totalSampleSize;

                // Print tensor properties
                print_tensor_properties(i, collProps.data.tensorCount);

                return static_cast<int>(i);
            }
        }

        return -1;
    }

    void print_tensor_properties(uint32_t collection_index, uint32_t tensor_count)
    {
        for (uint32_t t = 0; t < tensor_count; ++t)
        {
            // Chain DLPack properties to get full info
            XrTensorDlpackPropertiesNV dlpackProps{ XR_TYPE_TENSOR_DLPACK_PROPERTIES_NV };
            dlpackProps.next = nullptr;

            XrTensorPropertiesNV tensorProps{ XR_TYPE_TENSOR_PROPERTIES_NV };
            tensorProps.next = &dlpackProps;

            XrResult result = m_get_tensor_props_fn(m_tensor_list, collection_index, t, &tensorProps);
            if (result != XR_SUCCESS)
            {
                std::cerr << "  Failed to get tensor " << t << " properties" << std::endl;
                continue;
            }

            std::cout << "  Tensor " << t << ":" << std::endl;
            std::cout << "    Identifier: " << tensorProps.data.identifier << std::endl;
            std::cout << "    Data Type: " << tensorProps.data.dataType << std::endl;
            std::cout << "    Size: " << tensorProps.data.dataTypeSize << " bytes" << std::endl;
            std::cout << "    Offset: " << tensorProps.data.offset << std::endl;

            if (tensorProps.data.dataType == XR_TENSOR_DATA_TYPE_DLPACK_NV)
            {
                std::cout << "    DLPack Shape: [";
                for (int32_t d = 0; d < dlpackProps.data.ndim; ++d)
                {
                    if (d > 0)
                        std::cout << ", ";
                    std::cout << dlpackProps.data.shape[d];
                }
                std::cout << "]" << std::endl;
            }
        }
    }

    /*!
     * @brief Reads new samples from the target collection.
     * @param last_sample_index Reference to the last sample index read (updated on success).
     * @return Number of new samples read.
     */
    int read_samples(int64_t& last_sample_index)
    {
        if (m_target_collection_index < 0)
        {
            return 0;
        }

        // Prepare retrieval info
        XrTensorDataRetrievalInfoNV retrievalInfo{ XR_TYPE_TENSOR_DATA_RETRIEVAL_INFO_NV };
        retrievalInfo.next = nullptr;
        retrievalInfo.tensorCollectionIndex = static_cast<uint32_t>(m_target_collection_index);
        retrievalInfo.startSampleIndex = last_sample_index + 1; // Get samples after the last one we read

        // Prepare output buffers
        std::vector<XrTensorSampleMetadataNV> metadata(MAX_SAMPLES_PER_BATCH);
        std::vector<uint8_t> dataBuffer(MAX_SAMPLES_PER_BATCH * m_sample_batch_stride);

        XrTensorDataNV tensorData{ XR_TYPE_TENSOR_DATA_NV };
        tensorData.next = nullptr;
        tensorData.metadataArray = metadata.data();
        tensorData.metadataCapacity = MAX_SAMPLES_PER_BATCH;
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
            return 0;
        }

        if (tensorData.writtenSampleCount == 0)
        {
            return 0; // No new samples
        }

        // Process received samples
        for (uint32_t s = 0; s < tensorData.writtenSampleCount; ++s)
        {
            const auto& meta = metadata[s];
            const float* sample_data = reinterpret_cast<const float*>(dataBuffer.data() + s * m_sample_batch_stride);

            // Print sample info
            std::cout << "Sample " << meta.sampleIndex << " [" << std::fixed << std::setprecision(1) << sample_data[0]
                      << " ... " << sample_data[TENSOR_SIZE - 1] << "]" << std::endl;

            // Update last sample index
            if (meta.sampleIndex > last_sample_index)
            {
                last_sample_index = meta.sampleIndex;
            }
        }

        return static_cast<int>(tensorData.writtenSampleCount);
    }

    // OpenXR session
    std::shared_ptr<core::OpenXRSession> m_session;

    // Tensor list handle
    XrTensorListNV m_tensor_list{ XR_NULL_HANDLE };

    // Extension function pointers
    PFN_xrGetTensorListLatestGenerationNV m_get_latest_gen_fn{ nullptr };
    PFN_xrCreateTensorListNV m_create_list_fn{ nullptr };
    PFN_xrGetTensorListPropertiesNV m_get_list_props_fn{ nullptr };
    PFN_xrGetTensorCollectionPropertiesNV m_get_coll_props_fn{ nullptr };
    PFN_xrGetTensorPropertiesNV m_get_tensor_props_fn{ nullptr };
    PFN_xrGetTensorDataNV m_get_data_fn{ nullptr };
    PFN_xrUpdateTensorListNV m_update_list_fn{ nullptr };
    PFN_xrDestroyTensorListNV m_destroy_list_fn{ nullptr };

    // Target collection info
    std::string m_target_identifier;
    int m_target_collection_index{ -1 };
    uint32_t m_sample_batch_stride{ 0 };
    uint32_t m_sample_size{ 0 };
};

int main(int argc, char** argv)
{
    std::string target_identifier = "hello_tensor";

    // Parse command line arguments
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg.find("--plugin-root-id=") == 0)
        {
            target_identifier = arg.substr(17); // Length of "--plugin-root-id="
        }
    }

    std::signal(SIGINT, signal_handler);

    std::cout << "Hello Tensor Reader" << std::endl;
    std::cout << "Looking for collection: " << target_identifier << std::endl;

    try
    {
        HelloTensorReader reader(target_identifier);
        std::cout << "Reader running. Press Ctrl+C to stop." << std::endl;
        reader.run();
    }
    catch (const std::exception& e)
    {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "Goodbye!" << std::endl;
    return 0;
}
