// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tensor_types.hpp"

#include <oxr_utils/oxr_session_handles.hpp>

#include <XR_NVX1_tensor_data.h>
#include <memory>
#include <optional>
#include <vector>

namespace core
{
namespace tensorio
{

/*!
 * @brief Reads tensor data from the OpenXR runtime.
 *
 * This class provides an interface for discovering and reading tensor collections
 * from the OpenXR runtime using the XR_NVX1_tensor_data extension.
 *
 * Usage:
 * @code{cpp}
 * auto reader = TensorReader::create(session_handles);
 *
 * // Wait for collection to become available
 * while (reader->find_collection("my_tensors") < 0) {
 *     reader->update_list_if_needed();
 *     std::this_thread::sleep_for(100ms);
 * }
 *
 * int index = reader->find_collection("my_tensors");
 * auto samples = reader->read_samples(index, 0);
 * @endcode
 */
class TensorReader
{
public:
    /*!
     * @brief Creates a TensorReader instance.
     * @param handles OpenXR session handles from DeviceIOSession or OpenXRSession.
     * @return Unique pointer to the TensorReader.
     * @throws std::runtime_error if creation fails.
     */
    static std::unique_ptr<TensorReader> create(const OpenXRSessionHandles& handles);

    ~TensorReader();

    // Non-copyable, non-movable
    TensorReader(const TensorReader&) = delete;
    TensorReader& operator=(const TensorReader&) = delete;
    TensorReader(TensorReader&&) = delete;
    TensorReader& operator=(TensorReader&&) = delete;

    /*!
     * @brief Check if the tensor list needs update and refresh if needed.
     *
     * Compares the cached generation number with the runtime's current generation
     * and updates the list if they differ.
     *
     * @return true if the list was updated, false if no update was needed.
     */
    bool update_list_if_needed();

    /*!
     * @brief Force an update of the tensor list.
     * @return true on success, false on failure.
     */
    bool update_list();

    /*!
     * @brief Get the number of tensor collections available.
     * @return Number of collections.
     */
    uint32_t get_collection_count() const;

    /*!
     * @brief Find a collection by its identifier.
     * @param identifier The collection identifier to search for.
     * @return The collection index if found, -1 otherwise.
     */
    int find_collection(const std::string& identifier) const;

    /*!
     * @brief Get information about a tensor collection.
     * @param index The collection index.
     * @return Collection info if valid, std::nullopt otherwise.
     */
    std::optional<TensorCollectionInfo> get_collection_info(uint32_t index) const;

    /*!
     * @brief Get information about a tensor within a collection.
     * @param collection_index The collection index.
     * @param tensor_index The tensor index within the collection.
     * @return Tensor info if valid, std::nullopt otherwise.
     */
    std::optional<TensorInfo> get_tensor_info(uint32_t collection_index, uint32_t tensor_index) const;

    /*!
     * @brief Read samples from a tensor collection.
     * @param collection_index The collection index.
     * @param start_sample_index The sample index to start reading from.
     *        Use -1 for the latest sample, -N for the Nth most recent.
     * @param max_samples Maximum number of samples to read.
     * @return Vector of samples read (may be empty if no new samples).
     */
    std::vector<Sample> read_samples(uint32_t collection_index, int64_t start_sample_index, uint32_t max_samples = 16) const;

private:
    explicit TensorReader(const OpenXRSessionHandles& handles);

    void initialize_extension_functions();
    void create_tensor_list();

    // Session handles
    OpenXRSessionHandles m_handles;

    // Tensor list handle
    XrTensorListNV m_tensor_list{ XR_NULL_HANDLE };

    // Cached generation number
    uint64_t m_cached_generation{ 0 };

    // Extension function pointers
    PFN_xrGetTensorListLatestGenerationNV m_get_latest_gen_fn{ nullptr };
    PFN_xrCreateTensorListNV m_create_list_fn{ nullptr };
    PFN_xrGetTensorListPropertiesNV m_get_list_props_fn{ nullptr };
    PFN_xrGetTensorCollectionPropertiesNV m_get_coll_props_fn{ nullptr };
    PFN_xrGetTensorPropertiesNV m_get_tensor_props_fn{ nullptr };
    PFN_xrGetTensorDataNV m_get_data_fn{ nullptr };
    PFN_xrUpdateTensorListNV m_update_list_fn{ nullptr };
    PFN_xrDestroyTensorListNV m_destroy_list_fn{ nullptr };
};

} // namespace tensorio
} // namespace core
