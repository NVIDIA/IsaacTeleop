// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <oxr_utils/oxr_session_handles.hpp>

#include <XR_NVX1_tensor_data.h>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace core
{

/*!
 * @brief Configuration for SchemaTracker utility class.
 *
 * This struct contains all parameters needed to set up a tensor collection
 * for reading FlatBuffer schema data via OpenXR extensions.
 */
struct SchemaTrackerConfig
{
    //! Tensor collection identifier for discovery (e.g., "head_data").
    //! Both pusher and reader must use the same collection_id to communicate.
    std::string collection_id;

    //! Maximum serialized FlatBuffer message size in bytes.
    //! The tensor collection is created with this fixed buffer size.
    size_t max_flatbuffer_size;

    //! Tensor name within the collection (e.g., "head_pose").
    //! This identifies the specific tensor holding the serialized data.
    std::string tensor_identifier;

    //! Human-readable description for debugging and runtime display.
    std::string localized_name;
};

/*!
 * @brief Utility class for reading FlatBuffer schema data via OpenXR tensor extensions.
 *
 * This class handles all the OpenXR tensor extension calls for reading data.
 * Use it via composition in your ITrackerImpl implementations.
 *
 * The caller is responsible for creating the OpenXR session with the required extensions
 * (XR_NVX1_TENSOR_DATA_EXTENSION_NAME).
 *
 * Example usage with an ITracker subclass:
 * @code
 * class LocomotionTracker : public ITracker {
 * public:
 *     LocomotionTracker(const std::string& collection_id)
 *         : m_config({
 *             .collection_id = collection_id,
 *             .max_flatbuffer_size = 256,
 *             .tensor_identifier = "locomotion_command",
 *             .localized_name = "Locomotion Tracker"
 *         }) {}
 *
 *     std::vector<std::string> get_required_extensions() const override {
 *         return SchemaTracker::get_required_extensions();
 *     }
 *     std::string_view get_name() const override { return "LocomotionTracker"; }
 *     std::string_view get_schema_name() const override { return "core.LocomotionCommandRecord"; }
 *     std::string_view get_schema_text() const override {
 *         return std::string_view(
 *             reinterpret_cast<const char*>(LocomotionBinarySchema::data()),
 *             LocomotionBinarySchema::size());
 *     }
 *
 *     const LocomotionCommand& get_data(const DeviceIOSession& session) const {
 *         return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
 *     }
 *
 * private:
 *     std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override {
 *         return std::make_shared<Impl>(handles, m_config);
 *     }
 *
 *     SchemaTrackerConfig m_config;
 *
 *     class Impl : public ITrackerImpl {
 *     public:
 *         Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
 *             : m_schema_reader(handles, std::move(config)) {}
 *
 *         bool update(XrTime time) override {
 *             if (m_schema_reader.read_buffer(buffer_)) {
 *                 auto record = flatbuffers::GetRoot<LocomotionCommandRecord>(buffer_.data());
 *                 if (record && record->data()) {
 *                     data_ = *record->data();
 *                     return true;
 *                 }
 *             }
 *             return false;
 *         }
 *
 *         Timestamp serialize(flatbuffers::FlatBufferBuilder& builder,
 *                            size_t channel_index = 0) const override
 *         {
 *             LocomotionCommandRecordBuilder record_builder(builder);
 *             record_builder.add_data(&data_);
 *             builder.Finish(record_builder.Finish());
 *             return data_.timestamp();
 *         }
 *
 *         const LocomotionCommand& get_data() const { return data_; }
 *
 *     private:
 *         SchemaTracker m_schema_reader;
 *         std::vector<uint8_t> buffer_;
 *         LocomotionCommand data_;
 *     };
 * };
 * @endcode
 */
class SchemaTracker
{
public:
    /*!
     * @brief Constructs the tracker and initializes the OpenXR tensor list.
     * @param handles OpenXR session handles.
     * @param config Configuration for the tensor collection.
     * @throws std::runtime_error if initialization fails.
     */
    SchemaTracker(const OpenXRSessionHandles& handles, SchemaTrackerConfig config);

    /*!
     * @brief Destroys the tracker and cleans up OpenXR resources.
     */
    ~SchemaTracker();

    // Non-copyable, non-movable
    SchemaTracker(const SchemaTracker&) = delete;
    SchemaTracker& operator=(const SchemaTracker&) = delete;
    SchemaTracker(SchemaTracker&&) = delete;
    SchemaTracker& operator=(SchemaTracker&&) = delete;

    /*!
     * @brief Get required OpenXR extensions for tensor data reading.
     * @return Vector containing the tensor data extension name.
     */
    static std::vector<std::string> get_required_extensions();

    /*!
     * @brief Read the next available raw sample buffer.
     *
     * This method polls for tensor list updates, discovers the target collection
     * if not already connected, and retrieves the next available sample.
     *
     * @param buffer Output vector that will be resized and filled with sample data.
     * @return true if data was read, false if no new data available.
     */
    bool read_buffer(std::vector<uint8_t>& buffer);

    /*!
     * @brief Access the configuration.
     */
    const SchemaTrackerConfig& config() const;

private:
    void initialize_tensor_data_functions();
    void create_tensor_list();
    void poll_for_updates();
    std::optional<uint32_t> find_target_collection();
    bool read_next_sample(std::vector<uint8_t>& buffer);

    OpenXRSessionHandles m_handles;
    SchemaTrackerConfig m_config;

    XrTensorListNV m_tensor_list{ XR_NULL_HANDLE };

    PFN_xrGetTensorListLatestGenerationNV m_get_latest_gen_fn{ nullptr };
    PFN_xrCreateTensorListNV m_create_list_fn{ nullptr };
    PFN_xrGetTensorListPropertiesNV m_get_list_props_fn{ nullptr };
    PFN_xrGetTensorCollectionPropertiesNV m_get_coll_props_fn{ nullptr };
    PFN_xrGetTensorDataNV m_get_data_fn{ nullptr };
    PFN_xrUpdateTensorListNV m_update_list_fn{ nullptr };
    PFN_xrDestroyTensorListNV m_destroy_list_fn{ nullptr };

    std::optional<uint32_t> m_target_collection_index;
    uint32_t m_sample_batch_stride{ 0 };
    uint32_t m_sample_size{ 0 };

    uint64_t m_cached_generation{ 0 };

    std::optional<int64_t> m_last_sample_index;
};

} // namespace core
