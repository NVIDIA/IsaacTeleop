// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>

#include <XR_NVX1_push_tensor.h>
#include <atomic>
#include <memory>
#include <string>
#include <thread>

namespace plugins
{
namespace hello_tensor
{

/*!
 * @brief Demo plugin that pushes DLPack tensor data into the OpenXR runtime.
 *
 * This plugin demonstrates the full tensor push workflow using the XR_NVX1_push_tensor
 * extension. It creates a DLPack tensor collection (4x4 float32 matrix) and pushes
 * incrementing sample data at regular intervals.
 */
class HelloTensorPlugin
{
public:
    /*!
     * @brief Constructs the plugin and initializes the push tensor interface.
     * @param plugin_root_id Unique identifier for this plugin instance.
     * @throws std::runtime_error if initialization fails.
     */
    explicit HelloTensorPlugin(const std::string& plugin_root_id);

    ~HelloTensorPlugin();

    /*!
     * @brief Returns true if the worker thread has finished pushing samples.
     */
    bool is_done() const
    {
        return !m_running.load(std::memory_order_relaxed);
    }

    HelloTensorPlugin(const HelloTensorPlugin&) = delete;
    HelloTensorPlugin& operator=(const HelloTensorPlugin&) = delete;
    HelloTensorPlugin(HelloTensorPlugin&&) = delete;
    HelloTensorPlugin& operator=(HelloTensorPlugin&&) = delete;

private:
    /*!
     * @brief Worker thread that pushes tensor data samples.
     */
    void worker_thread();

    /*!
     * @brief Initializes push tensor extension function pointers.
     * @throws std::runtime_error if extension functions cannot be loaded.
     */
    void initialize_push_tensor_functions();

    /*!
     * @brief Creates a DLPack tensor collection.
     * @throws std::runtime_error if tensor collection creation fails.
     */
    void create_tensor_collection();

    /*!
     * @brief Pushes a sample of tensor data with incrementing values.
     * @param sample_count The current sample count (used to generate data).
     */
    void push_sample(int sample_count);

    // OpenXR session
    std::shared_ptr<core::OpenXRSession> m_session;

    // Push tensor collection handle
    XrPushTensorCollectionNV m_push_tensor{ XR_NULL_HANDLE };

    // Tensor collection ID assigned by runtime
    XrTensorCollectionIDNV m_tensor_collection_id{ 0 };

    // Extension function pointers
    PFN_xrCreatePushTensorCollectionNV m_create_fn{ nullptr };
    PFN_xrPushTensorCollectionDataNV m_push_fn{ nullptr };
    PFN_xrDestroyPushTensorCollectionNV m_destroy_fn{ nullptr };

    // Worker thread and control
    std::thread m_thread;
    std::atomic<bool> m_running{ false };

    // Plugin identifier
    std::string m_root_id;

    // Tensor dimensions (4x4 float32 matrix)
    static constexpr int TENSOR_ROWS = 4;
    static constexpr int TENSOR_COLS = 4;
    static constexpr int TENSOR_SIZE = TENSOR_ROWS * TENSOR_COLS;
};

} // namespace hello_tensor
} // namespace plugins
