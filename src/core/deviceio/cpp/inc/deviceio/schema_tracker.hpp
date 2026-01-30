// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace core
{

/*!
 * @brief Configuration for SchemaTracker classes.
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
 * @brief Base class for trackers that read FlatBuffer schema data via OpenXR tensor extensions.
 *
 * This class integrates with the ITracker interface, allowing schema-based trackers
 * to be used alongside standard device trackers (HeadTracker, HandTracker, etc.)
 * within a DeviceIOSession.
 *
 * The caller is responsible for creating the OpenXR session with the required extensions
 * (XR_NVX1_TENSOR_DATA_EXTENSION_NAME).
 *
 * Example subclass:
 * @code
 * class LocomotionTracker : public SchemaTracker {
 * public:
 *     LocomotionTracker(const std::string& collection_id)
 *         : SchemaTracker({
 *             .collection_id = collection_id,
 *             .max_flatbuffer_size = 256,
 *             .tensor_identifier = "locomotion_command",
 *             .localized_name = "Locomotion Tracker"
 *         }) {}
 *
 *     std::string_view get_name() const override { return "LocomotionTracker"; }
 *     std::string_view get_schema_name() const override { return "core.LocomotionCommand"; }
 *     std::string_view get_schema_text() const override {
 *         return std::string_view(
 *             reinterpret_cast<const char*>(LocomotionBinarySchema::data()),
 *             LocomotionBinarySchema::size());
 *     }
 *
 *     const LocomotionCommandT& get_data(const DeviceIOSession& session) const {
 *         return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
 *     }
 *
 * private:
 *     std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override {
 *         return std::make_shared<Impl>(handles, get_config());
 *     }
 *
 *     class Impl : public SchemaTracker::Impl {
 *     public:
 *         Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
 *             : SchemaTracker::Impl(handles, std::move(config)) {}
 *
 *         bool update(XrTime time) override {
 *             if (read_buffer(buffer_)) {
 *                 auto fb = GetLocomotionCommand(buffer_.data());
 *                 if (fb) {
 *                     fb->UnPackTo(&data_);
 *                     return true;
 *                 }
 *             }
 *             return false;
 *         }
 *
 *         Timestamp serialize(flatbuffers::FlatBufferBuilder& builder) const override {
 *             auto offset = LocomotionCommand::Pack(builder, &data_);
 *             builder.Finish(offset);
 *             return data_.timestamp ? *data_.timestamp : Timestamp{};
 *         }
 *
 *         const LocomotionCommandT& get_data() const { return data_; }
 *
 *     private:
 *         std::vector<uint8_t> buffer_;
 *         LocomotionCommandT data_;
 *     };
 * };
 * @endcode
 */
class SchemaTracker : public ITracker
{
public:
    //! Required OpenXR extensions for reading tensor data
    static constexpr const char* REQUIRED_EXTENSIONS[] = { "XR_NVX1_tensor_data" };
    static constexpr size_t REQUIRED_EXTENSIONS_COUNT = 1;

    /*!
     * @brief Constructs the tracker with configuration.
     * @param config Configuration for the tensor collection to discover.
     */
    explicit SchemaTracker(SchemaTrackerConfig config);

    /*!
     * @brief Virtual destructor for proper cleanup.
     */
    virtual ~SchemaTracker() = default;

    // Non-copyable, non-movable
    SchemaTracker(const SchemaTracker&) = delete;
    SchemaTracker& operator=(const SchemaTracker&) = delete;
    SchemaTracker(SchemaTracker&&) = delete;
    SchemaTracker& operator=(SchemaTracker&&) = delete;

    /*!
     * @brief Get required OpenXR extensions (includes tensor data extension).
     */
    std::vector<std::string> get_required_extensions() const override;

    // Subclasses must implement these from ITracker:
    // virtual std::string_view get_name() const = 0;
    // virtual std::string_view get_schema_name() const = 0;
    // virtual std::string_view get_schema_text() const = 0;

protected:
    /*!
     * @brief Access the configuration for subclass use.
     */
    const SchemaTrackerConfig& get_config() const;

    /*!
     * @brief Base implementation for schema trackers that read from tensor extensions.
     *
     * Subclasses should inherit from this and implement:
     * - update(XrTime time): Call read_buffer() and deserialize the FlatBuffer
     * - serialize(): Serialize the current data to a FlatBuffer
     */
    class Impl : public ITrackerImpl
    {
    public:
        /*!
         * @brief Constructs the implementation and initializes the OpenXR tensor list.
         * @param handles OpenXR session handles.
         * @param config Configuration for the tensor collection.
         * @throws std::runtime_error if initialization fails.
         */
        Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config);

        /*!
         * @brief Destroys the implementation and cleans up OpenXR resources.
         */
        virtual ~Impl();

        // Non-copyable, non-movable
        Impl(const Impl&) = delete;
        Impl& operator=(const Impl&) = delete;
        Impl(Impl&&) = delete;
        Impl& operator=(Impl&&) = delete;

        /*!
         * @brief Check if the target tensor collection has been discovered.
         * @return true if connected to the target collection, false otherwise.
         */
        bool is_connected() const;

        /*!
         * @brief Returns the number of samples successfully read.
         */
        size_t get_read_count() const;

    protected:
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
         * @brief Access the configuration for subclass use.
         */
        const SchemaTrackerConfig& config() const;

    private:
        class ImplData;
        std::unique_ptr<ImplData> m_data;
    };

private:
    SchemaTrackerConfig m_config;
};

} // namespace core
