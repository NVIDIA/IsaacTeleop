// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file hello_tensor_reader.cpp
 * @brief Demo application that reads tensor data using the TensorIO library.
 *
 * This example demonstrates how to use the TensorReader class to discover
 * and read tensor collections from the OpenXR runtime.
 */

#include <oxr/oxr_session.hpp>
#include <tensorio/tensor_reader.hpp>
#include <tensorio/tensor_types.hpp>

#include <XR_NVX1_tensor_data.h>
#include <atomic>
#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <thread>

using namespace core::tensorio;

static_assert(ATOMIC_BOOL_LOCK_FREE, "lock-free atomic bool is required for signal safety");

std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

// Expected tensor dimensions (4x4 float32 matrix, matching the pusher)
static constexpr int TENSOR_ROWS = 4;
static constexpr int TENSOR_COLS = 4;
static constexpr int TENSOR_SIZE = TENSOR_ROWS * TENSOR_COLS;
static constexpr int MAX_SAMPLES = 100;
static constexpr uint32_t MAX_SAMPLES_PER_BATCH = 16;

int main(int argc, char** argv)
{
    std::string target_identifier = "hello_tensor";

    // Parse command line arguments
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg.find("--plugin-root-id=") == 0)
        {
            target_identifier = arg.substr(17);
        }
    }

    std::signal(SIGINT, signal_handler);

    std::cout << "Hello Tensor Reader (using TensorIO library)" << std::endl;
    std::cout << "Looking for collection: " << target_identifier << std::endl;

    try
    {
        // Create OpenXR session with tensor data extension
        std::vector<std::string> extensions = { XR_NVX1_TENSOR_DATA_EXTENSION_NAME };

        auto session = core::OpenXRSession::Create("HelloTensorReader", extensions);
        if (!session)
        {
            std::cerr << "Failed to create OpenXR session" << std::endl;
            return 1;
        }

        // Create the reader
        auto reader = TensorReader::create(session->get_handles());

        std::cout << "TensorReader initialized successfully" << std::endl;
        std::cout << "Waiting for tensor collection... Press Ctrl+C to stop." << std::endl;

        int64_t last_sample_index = -1;
        int samples_received = 0;
        int target_collection_index = -1;

        while (!g_stop_requested.load(std::memory_order_relaxed) && samples_received < MAX_SAMPLES)
        {
            // Update tensor list if needed
            reader->update_list_if_needed();

            // Find target collection if not found yet
            if (target_collection_index < 0)
            {
                target_collection_index = reader->find_collection(target_identifier);
                if (target_collection_index < 0)
                {
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    continue;
                }

                // Print collection info
                auto coll_info = reader->get_collection_info(target_collection_index);
                if (coll_info.has_value())
                {
                    std::cout << "\nFound tensor collection:" << std::endl;
                    std::cout << "  Index: " << target_collection_index << std::endl;
                    std::cout << "  Identifier: " << coll_info->identifier << std::endl;
                    std::cout << "  Localized Name: " << coll_info->localized_name << std::endl;
                    std::cout << "  Tensor Count: " << coll_info->tensor_count << std::endl;
                    std::cout << "  Sample Size: " << coll_info->total_sample_size << " bytes" << std::endl;
                    std::cout << "  Batch Stride: " << coll_info->sample_batch_stride << " bytes" << std::endl;

                    // Print tensor properties
                    for (uint32_t t = 0; t < coll_info->tensor_count; ++t)
                    {
                        auto tensor_info = reader->get_tensor_info(target_collection_index, t);
                        if (tensor_info.has_value())
                        {
                            std::cout << "  Tensor " << t << ":" << std::endl;
                            std::cout << "    Identifier: " << tensor_info->identifier << std::endl;
                            std::cout << "    Data Type: " << tensor_info->data_type << std::endl;
                            std::cout << "    Size: " << tensor_info->data_type_size << " bytes" << std::endl;
                            std::cout << "    Offset: " << tensor_info->offset << std::endl;

                            if (tensor_info->dlpack_info.has_value())
                            {
                                const auto& dlpack = tensor_info->dlpack_info.value();
                                std::cout << "    DLPack Shape: [";
                                for (int32_t d = 0; d < dlpack.ndim; ++d)
                                {
                                    if (d > 0)
                                        std::cout << ", ";
                                    std::cout << dlpack.shape[d];
                                }
                                std::cout << "]" << std::endl;
                            }
                        }
                    }
                    std::cout << std::endl;
                }
            }

            // Read new samples
            auto samples = reader->read_samples(target_collection_index, last_sample_index + 1, MAX_SAMPLES_PER_BATCH);

            if (!samples.empty())
            {
                for (const auto& sample : samples)
                {
                    const float* sample_data = reinterpret_cast<const float*>(sample.data.data());
                    std::cout << "Sample " << sample.sample_index << " [" << std::fixed << std::setprecision(1)
                              << sample_data[0] << " ... " << sample_data[TENSOR_SIZE - 1] << "]" << std::endl;

                    if (sample.sample_index > last_sample_index)
                    {
                        last_sample_index = sample.sample_index;
                    }
                }
                samples_received += static_cast<int>(samples.size());
            }
            else
            {
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
        }

        if (samples_received >= MAX_SAMPLES)
        {
            std::cout << "\nRead loop finished after " << samples_received << " samples (limit reached)" << std::endl;
        }
        else
        {
            std::cout << "\nRead loop finished. Total samples received: " << samples_received << std::endl;
        }
    }
    catch (const std::exception& e)
    {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "Goodbye!" << std::endl;
    return 0;
}
