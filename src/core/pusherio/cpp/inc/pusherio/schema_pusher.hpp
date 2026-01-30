// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <oxr_utils/oxr_session_handles.hpp>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace core
{

/*!
 * @brief Configuration for Pusher classes.
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
 * @brief Base class for pushing FlatBuffer schema data via OpenXR tensor extensions.
 *
 * This class uses externally-provided OpenXR session handles and handles tensor collection
 * creation and sample pushing logic. Subclasses provide typed `push()` methods that serialize
 * their specific FlatBuffer types and call `push_buffer()`.
 *
 * The caller is responsible for creating the OpenXR session with the required extensions
 * (XR_NVX1_PUSH_TENSOR_EXTENSION_NAME, XR_NVX1_TENSOR_DATA_EXTENSION_NAME) and passing
 * the handles to this class.
 *
 * Example subclass:
 * @code
 * class HeadPosePusher : public SchemaPusherBase {
 * public:
 *     HeadPosePusher(const OpenXRSessionHandles& handles, const std::string& collection_id)
 *         : SchemaPusherBase(handles, {
 *             .collection_id = collection_id,
 *             .max_flatbuffer_size = 256,
 *             .tensor_identifier = "head_pose",
 *             .localized_name = "HeadPose Data"
 *         }) {}
 *
 *     bool push(const HeadPoseT& data) {
 *         flatbuffers::FlatBufferBuilder builder(config().max_flatbuffer_size);
 *         auto offset = HeadPose::Pack(builder, &data);
 *         builder.Finish(offset);
 *         return push_buffer(builder.GetBufferPointer(), builder.GetSize());
 *     }
 * };
 * @endcode
 */
class SchemaPusherBase
{
public:
    //! Required OpenXR extensions for pushing tensor data
    static constexpr const char* REQUIRED_EXTENSIONS[] = { "XR_NVX1_push_tensor", "XR_NVX1_tensor_data" };
    static constexpr size_t REQUIRED_EXTENSIONS_COUNT = std::size(REQUIRED_EXTENSIONS);

    /*!
     * @brief Constructs the pusher and initializes the OpenXR tensor collection.
     * @param handles OpenXR session handles (caller must create session with required extensions).
     * @param config Configuration for the tensor collection.
     * @throws std::runtime_error if initialization fails.
     */
    SchemaPusherBase(const OpenXRSessionHandles& handles, SchemaPusherConfig config);

    /*!
     * @brief Destroys the pusher and cleans up OpenXR resources.
     */
    virtual ~SchemaPusherBase();

    // Non-copyable, non-movable
    SchemaPusherBase(const SchemaPusherBase&) = delete;
    SchemaPusherBase& operator=(const SchemaPusherBase&) = delete;
    SchemaPusherBase(SchemaPusherBase&&) = delete;
    SchemaPusherBase& operator=(SchemaPusherBase&&) = delete;

    /*!
     * @brief Returns the number of samples successfully pushed.
     */
    size_t get_push_count() const;

protected:
    /*!
     * @brief Push raw serialized FlatBuffer data.
     *
     * Subclasses call this after serializing their FlatBuffer message.
     * The buffer will be padded to max_flatbuffer_size if smaller.
     *
     * @param buffer Pointer to serialized FlatBuffer data.
     * @param size Size of the serialized data in bytes.
     * @return true on success, false on failure.
     */
    bool push_buffer(const uint8_t* buffer, size_t size);

    /*!
     * @brief Access the configuration for subclass use.
     */
    const SchemaPusherConfig& config() const;

private:
    class Impl;
    std::unique_ptr<Impl> m_impl;
};

} // namespace core
