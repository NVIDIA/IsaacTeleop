// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <XR_NVX1_push_tensor.h>
#include <XR_NVX1_tensor_data.h>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace core
{

/*!
 * @brief Configuration for SchemaPusher.
 *
 * This struct contains all parameters needed to set up a tensor collection
 * for pushing FlatBuffer schema data via OpenXR extensions.
 */
struct SchemaPusherConfig
{
    //! Tensor collection identifier for discovery (e.g., "head_data").
    //! Both pusher and reader must use the same collection_id to communicate.
    std::string collection_id;

    //! Maximum serialized FlatBuffer message size in bytes.
    //! The tensor collection is created with this fixed buffer size.
    //! Serialized messages larger than this will be rejected.
    size_t max_flatbuffer_size;

    //! Tensor name within the collection (e.g., "head_pose").
    //! This identifies the specific tensor holding the serialized data.
    std::string tensor_identifier;

    //! Human-readable description for debugging and runtime display.
    std::string localized_name;

    //! OpenXR application name. If empty, defaults to "Pusher" or "Reader".
    std::string app_name = "";
};


/*!
 * @brief Pushes FlatBuffer schema data via OpenXR tensor extensions.
 *
 * This class uses externally-provided OpenXR session handles and handles tensor collection
 * creation and sample pushing logic. Use composition to wrap this class with typed push methods.
 *
 * The caller is responsible for creating the OpenXR session with the required extensions
 * (XR_NVX1_PUSH_TENSOR_EXTENSION_NAME, XR_NVX1_TENSOR_DATA_EXTENSION_NAME) and passing
 * the handles to this class.
 *
 * Example usage with composition:
 * @code
 * class HeadPosePusher {
 * public:
 *     HeadPosePusher(const OpenXRSessionHandles& handles, const std::string& collection_id)
 *         : m_pusher(handles, {
 *             .collection_id = collection_id,
 *             .max_flatbuffer_size = 256,
 *             .tensor_identifier = "head_pose",
 *             .localized_name = "HeadPose Data"
 *         }) {}
 *
 *     bool push(const HeadPoseT& data) {
 *         flatbuffers::FlatBufferBuilder builder(m_pusher.config().max_flatbuffer_size);
 *         auto offset = HeadPose::Pack(builder, &data);
 *         builder.Finish(offset);
 *         return m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
 *     }
 *
 *     size_t get_push_count() const { return m_pusher.get_push_count(); }
 *
 * private:
 *     SchemaPusher m_pusher;
 * };
 * @endcode
 */
class SchemaPusher
{
public:
    /*!
     * @brief Get required OpenXR extensions for pushing tensor data.
     *
     * Includes platform-specific time conversion extension.
     */
    static std::vector<std::string> get_required_extensions()
    {
#if defined(XR_USE_PLATFORM_WIN32)
        return { "XR_NVX1_push_tensor", "XR_NVX1_tensor_data", "XR_KHR_win32_convert_performance_counter_time" };
#elif defined(XR_USE_TIMESPEC)
        return { "XR_NVX1_push_tensor", "XR_NVX1_tensor_data", "XR_KHR_convert_timespec_time" };
#else
        return { "XR_NVX1_push_tensor", "XR_NVX1_tensor_data" };
#endif
    }

    /*!
     * @brief Constructs the pusher and initializes the OpenXR tensor collection.
     * @param handles OpenXR session handles (caller must create session with required extensions).
     * @param config Configuration for the tensor collection.
     * @throws std::runtime_error if initialization fails.
     */
    SchemaPusher(const OpenXRSessionHandles& handles, SchemaPusherConfig config);

    /*!
     * @brief Destroys the pusher and cleans up OpenXR resources.
     */
    ~SchemaPusher();

    // Non-copyable, non-movable
    SchemaPusher(const SchemaPusher&) = delete;
    SchemaPusher& operator=(const SchemaPusher&) = delete;
    SchemaPusher(SchemaPusher&&) = delete;
    SchemaPusher& operator=(SchemaPusher&&) = delete;

    /*!
     * @brief Push raw serialized FlatBuffer data.
     *
     * The buffer will be padded to max_flatbuffer_size if smaller.
     *
     * @param buffer Pointer to serialized FlatBuffer data.
     * @param size Size of the serialized data in bytes.
     * @return true on success, false on failure.
     */
    bool push_buffer(const uint8_t* buffer, size_t size);

    /*!
     * @brief Returns the number of samples successfully pushed.
     */
    size_t get_push_count() const;

    /*!
     * @brief Access the configuration.
     */
    const SchemaPusherConfig& config() const;

private:
    void initialize_push_tensor_functions();
    void create_tensor_collection();

    OpenXRSessionHandles m_handles;
    SchemaPusherConfig m_config;
    XrTimeConverter m_time_converter;

    // Push tensor collection handle
    XrPushTensorCollectionNV m_push_tensor{ XR_NULL_HANDLE };
    XrTensorCollectionIDNV m_tensor_collection_id{ 0 };

    // Extension function pointers
    PFN_xrCreatePushTensorCollectionNV m_create_fn{ nullptr };
    PFN_xrPushTensorCollectionDataNV m_push_fn{ nullptr };
    PFN_xrDestroyPushTensorCollectionNV m_destroy_fn{ nullptr };

    // Statistics
    size_t m_push_count{ 0 };
};

} // namespace core
