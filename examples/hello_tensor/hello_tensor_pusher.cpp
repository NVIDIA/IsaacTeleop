// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file hello_tensor_pusher.cpp
 * @brief Demo application that pushes tensor data using the TensorIO library.
 *
 * This example demonstrates how to use the TensorPusher class to push
 * DLPack-formatted tensor data into the OpenXR runtime.
 */

#include <oxr/oxr_session.hpp>
#include <tensorio/tensor_pusher.hpp>
#include <tensorio/tensor_types.hpp>

#include <XR_NVX1_push_tensor.h>
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

// Tensor dimensions (4x4 float32 matrix)
static constexpr int TENSOR_ROWS = 4;
static constexpr int TENSOR_COLS = 4;
static constexpr int TENSOR_SIZE = TENSOR_ROWS * TENSOR_COLS;
static constexpr int MAX_SAMPLES = 100;

int main(int argc, char** argv)
{
    std::string collection_id = "hello_tensor";

    // Parse command line arguments
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg.find("--plugin-root-id=") == 0)
        {
            collection_id = arg.substr(17);
        }
    }

    std::signal(SIGINT, signal_handler);

    std::cout << "Hello Tensor Pusher (using TensorIO library)" << std::endl;
    std::cout << "Collection ID: " << collection_id << std::endl;

    try
    {
        // Create OpenXR session with tensor extensions
        std::vector<std::string> extensions = { XR_NVX1_PUSH_TENSOR_EXTENSION_NAME, XR_NVX1_TENSOR_DATA_EXTENSION_NAME };

        auto session = core::OpenXRSession::Create("HelloTensorPusher", extensions);
        if (!session)
        {
            std::cerr << "Failed to create OpenXR session" << std::endl;
            return 1;
        }

        // Configure the tensor collection
        TensorCollectionConfig config;
        config.identifier = collection_id;
        config.localized_name = "Hello Tensor Demo";
        config.total_sample_size = TENSOR_SIZE * sizeof(float);

        // Add a 4x4 float32 DLPack tensor
        TensorSpec tensor_spec;
        tensor_spec.identifier = "hello_matrix";
        tensor_spec.data_type = XR_TENSOR_DATA_TYPE_DLPACK_NV;
        tensor_spec.data_type_size = TENSOR_SIZE * sizeof(float);

        DlpackInfo dlpack;
        dlpack.dtype = DlpackInfo::dtype_float32();
        dlpack.ndim = 2;
        dlpack.shape[0] = TENSOR_ROWS;
        dlpack.shape[1] = TENSOR_COLS;
        dlpack.strides[0] = TENSOR_COLS * sizeof(float);
        dlpack.strides[1] = sizeof(float);
        tensor_spec.dlpack_info = dlpack;

        config.tensors.push_back(tensor_spec);

        // Create the pusher
        auto pusher = TensorPusher::create(session->get_handles(), config);

        std::cout << "Tensor collection created successfully" << std::endl;
        std::cout << "  Collection ID: " << pusher->get_collection_id() << std::endl;
        std::cout << "  Identifier: " << pusher->get_identifier() << std::endl;
        std::cout << "  Shape: [" << TENSOR_ROWS << ", " << TENSOR_COLS << "]" << std::endl;
        std::cout << "  Data Type: DLPack float32" << std::endl;

        std::cout << "\nPushing samples every 50ms. Press Ctrl+C to stop." << std::endl;

        int sample_count = 0;
        while (!g_stop_requested.load(std::memory_order_relaxed) && sample_count < MAX_SAMPLES)
        {
            // Create sample data: 4x4 matrix with incrementing values
            float data[TENSOR_SIZE];
            for (int i = 0; i < TENSOR_SIZE; ++i)
            {
                data[i] = static_cast<float>(sample_count * TENSOR_SIZE + i);
            }

            // Push the data
            if (pusher->push(data))
            {
                std::cout << "Pushed sample " << sample_count << " [" << std::fixed << std::setprecision(1) << data[0]
                          << " ... " << data[TENSOR_SIZE - 1] << "]" << std::endl;
            }

            sample_count++;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        std::cout << "\nFinished after " << sample_count << " samples" << std::endl;
    }
    catch (const std::exception& e)
    {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "Goodbye!" << std::endl;
    return 0;
}
