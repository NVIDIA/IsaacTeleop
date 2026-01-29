// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tensor_types.hpp"

#include <oxr_utils/oxr_session_handles.hpp>

#include <XR_NVX1_push_tensor.h>
#include <chrono>
#include <memory>

namespace core
{
namespace tensorio
{

/*!
 * @brief Pushes tensor data into the OpenXR runtime.
 *
 * This class provides an interface for pushing DLPack-formatted tensor data
 * into the OpenXR runtime using the XR_NVX1_push_tensor extension.
 *
 * Usage:
 * @code{cpp}
 * TensorCollectionConfig config;
 * config.identifier = "my_tensors";
 * config.localized_name = "My Tensor Collection";
 * // ... configure tensors ...
 *
 * auto pusher = TensorPusher::create(session_handles, config);
 * pusher->push(data_buffer, buffer_size);
 * @endcode
 */
class TensorPusher
{
public:
    /*!
     * @brief Creates a TensorPusher instance.
     * @param handles OpenXR session handles from DeviceIOSession or OpenXRSession.
     * @param config Configuration for the tensor collection to create.
     * @return Unique pointer to the TensorPusher, or nullptr on failure.
     * @throws std::runtime_error if creation fails.
     */
    static std::unique_ptr<TensorPusher> create(const OpenXRSessionHandles& handles,
                                                const TensorCollectionConfig& config);

    ~TensorPusher();

    // Non-copyable, non-movable
    TensorPusher(const TensorPusher&) = delete;
    TensorPusher& operator=(const TensorPusher&) = delete;
    TensorPusher(TensorPusher&&) = delete;
    TensorPusher& operator=(TensorPusher&&) = delete;

    /*!
     * @brief Push raw buffer data as a tensor sample.
     * @param buffer Pointer to the tensor data.
     * @param buffer_size Size of the buffer in bytes.
     * @param timestamp OpenXR timestamp (0 to use current time).
     * @param raw_device_timestamp Raw device timestamp in nanoseconds (0 to use current time).
     * @return true on success, false on failure.
     */
    bool push(const uint8_t* buffer, uint32_t buffer_size, XrTime timestamp = 0, uint64_t raw_device_timestamp = 0);

    /*!
     * @brief Push typed data as a tensor sample.
     * @tparam T Element type (e.g., float, int32_t).
     * @param data Vector of data elements.
     * @param timestamp OpenXR timestamp (0 to use current time).
     * @return true on success, false on failure.
     */
    template <typename T>
    bool push(const std::vector<T>& data, XrTime timestamp = 0)
    {
        return push(
            reinterpret_cast<const uint8_t*>(data.data()), static_cast<uint32_t>(data.size() * sizeof(T)), timestamp);
    }

    /*!
     * @brief Push a C-style array as a tensor sample.
     * @tparam T Element type.
     * @tparam N Array size.
     * @param data Array of data elements.
     * @param timestamp OpenXR timestamp (0 to use current time).
     * @return true on success, false on failure.
     */
    template <typename T, size_t N>
    bool push(const T (&data)[N], XrTime timestamp = 0)
    {
        return push(reinterpret_cast<const uint8_t*>(data), static_cast<uint32_t>(N * sizeof(T)), timestamp);
    }

    /*!
     * @brief Get the tensor collection ID assigned by the runtime.
     * @return The tensor collection ID.
     */
    XrTensorCollectionIDNV get_collection_id() const
    {
        return m_tensor_collection_id;
    }

    /*!
     * @brief Get the identifier string for this collection.
     * @return The collection identifier.
     */
    const std::string& get_identifier() const
    {
        return m_identifier;
    }

private:
    TensorPusher(const OpenXRSessionHandles& handles, const TensorCollectionConfig& config);

    void initialize_extension_functions();
    void create_tensor_collection(const TensorCollectionConfig& config);

    // Session handles
    OpenXRSessionHandles m_handles;

    // Push tensor collection handle
    XrPushTensorCollectionNV m_push_tensor{ XR_NULL_HANDLE };

    // Tensor collection ID assigned by runtime
    XrTensorCollectionIDNV m_tensor_collection_id{ 0 };

    // Extension function pointers
    PFN_xrCreatePushTensorCollectionNV m_create_fn{ nullptr };
    PFN_xrPushTensorCollectionDataNV m_push_fn{ nullptr };
    PFN_xrDestroyPushTensorCollectionNV m_destroy_fn{ nullptr };

    // Collection identifier
    std::string m_identifier;
};

} // namespace tensorio
} // namespace core
