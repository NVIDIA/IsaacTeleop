// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_session/deviceio_session.hpp"

#include <live_trackers/live_deviceio_factory.hpp>
#include <mcap/reader.hpp>
#include <mcap/writer.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/os_time.hpp>

#include <cassert>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <unordered_map>

namespace core
{

// ============================================================================
// DeviceIOSession Implementation
// ============================================================================

namespace
{

// Identify a tracker in an error message by its name, tolerating a null pointer.
std::string tracker_name_for_error(const ITracker* tracker)
{
    return tracker ? std::string(tracker->get_name()) : std::string("<null>");
}

bool tracker_in_list(const std::vector<std::shared_ptr<ITracker>>& trackers, const ITracker* tracker_ptr)
{
    for (const auto& t : trackers)
    {
        if (t.get() == tracker_ptr)
            return true;
    }
    return false;
}

using ChannelIdMap = std::unordered_map<mcap::ChannelId, mcap::ChannelId>;

ChannelIdMap register_mcap_channels(mcap::McapReader& input, mcap::McapWriter& output)
{
    std::unordered_map<mcap::SchemaId, mcap::SchemaId> schema_ids;
    for (const auto& [old_id, source] : input.schemas())
    {
        mcap::Schema schema(source->name, source->encoding, source->data);
        output.addSchema(schema);
        schema_ids.emplace(old_id, schema.id);
    }
    ChannelIdMap channel_ids;
    for (const auto& [old_id, source] : input.channels())
    {
        const auto schema_it = schema_ids.find(source->schemaId);
        const auto new_schema_id = schema_it == schema_ids.end() ? 0 : schema_it->second;
        mcap::Channel channel(source->topic, source->messageEncoding, new_schema_id, source->metadata);
        output.addChannel(channel);
        channel_ids.emplace(old_id, channel.id);
    }
    return channel_ids;
}

void write_merged_message(const mcap::MessageView& view, const ChannelIdMap& channel_ids, mcap::McapWriter& output)
{
    mcap::Message message = view.message;
    message.channelId = channel_ids.at(view.message.channelId);
    const auto status = output.write(message);
    if (!status.ok())
        throw std::runtime_error("DeviceIOSession: failed to merge MCAP media: " + status.message);
}

std::unique_ptr<mcap::McapReader> open_mcap_reader(const std::string& filename)
{
    auto input = std::make_unique<mcap::McapReader>();
    const auto open_status = input->open(filename);
    if (!open_status.ok())
        throw std::runtime_error("DeviceIOSession: cannot read MCAP fragment '" + filename + "': " + open_status.message);
    return input;
}

void merge_messages_by_log_time(mcap::McapReader& recording,
                                const ChannelIdMap& recording_channels,
                                mcap::McapReader& media,
                                const ChannelIdMap& media_channels,
                                mcap::McapWriter& output)
{
    const auto on_problem = [](const mcap::Status& status)
    { throw std::runtime_error("DeviceIOSession: " + status.message); };
    auto recording_messages = recording.readMessages(on_problem);
    auto media_messages = media.readMessages(on_problem);
    auto recording_it = recording_messages.begin();
    auto media_it = media_messages.begin();
    while (recording_it != recording_messages.end() || media_it != media_messages.end())
    {
        if (media_it == media_messages.end() ||
            (recording_it != recording_messages.end() && recording_it->message.logTime <= media_it->message.logTime))
        {
            write_merged_message(*recording_it, recording_channels, output);
            ++recording_it;
        }
        else
        {
            write_merged_message(*media_it, media_channels, output);
            ++media_it;
        }
    }
}

void merge_embedded_media(const std::string& recording_filename, const std::string& media_filename)
{
    if (!std::filesystem::exists(media_filename))
        throw std::runtime_error("DeviceIOSession: embedded media fragment is missing: " + media_filename);
    const std::string temporary_filename = recording_filename + ".merge.partial";
    mcap::McapWriter output;
    mcap::McapWriterOptions options("teleop");
    options.compression = mcap::Compression::None;
    const auto open_status = output.open(temporary_filename, options);
    if (!open_status.ok())
        throw std::runtime_error("DeviceIOSession: cannot create merged MCAP: " + open_status.message);
    try
    {
        auto recording = open_mcap_reader(recording_filename);
        auto media = open_mcap_reader(media_filename);
        const auto recording_channels = register_mcap_channels(*recording, output);
        const auto media_channels = register_mcap_channels(*media, output);
        merge_messages_by_log_time(*recording, recording_channels, *media, media_channels, output);
        output.close();
        std::filesystem::rename(temporary_filename, recording_filename);
        std::filesystem::remove(media_filename);
    }
    catch (...)
    {
        output.terminate();
        throw;
    }
}

// Fully validate a vendor config against the session's tracker list before anything consumes it.
// DeviceIOSession is the single owner of vendor validation: the live factory assumes a validated
// config and treats an invalid one as undefined behavior. Two parts: the tracker-list presence
// check (done here since the session holds the list) and the dispatch-driven vendor-validity check
// (delegated to validate_vendor_selections(), which owns the vendor dispatch table).
void validate_vendor_config(const std::vector<std::shared_ptr<ITracker>>& trackers,
                            const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors)
{
    for (const auto& [tracker_ptr, vendor] : tracker_vendors)
    {
        if (!tracker_in_list(trackers, tracker_ptr))
        {
            throw std::invalid_argument("DeviceIOSession: vendor selection '" + vendor.id + "' references tracker '" +
                                        tracker_name_for_error(tracker_ptr) + "' that is not in the trackers list");
        }
    }
    validate_vendor_selections(tracker_vendors);
}

} // namespace

DeviceIOSession::DeviceIOSession(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                 const OpenXRSessionHandles& handles,
                                 std::optional<McapRecordingConfig> recording_config,
                                 VendorConfig vendor_config)
    : handles_(handles)
{
    std::vector<std::pair<const ITracker*, std::string>> tracker_names;

    // Validate up front, before the MCAP writer opens below, so an invalid config leaves no
    // stray recording file on disk.
    validate_vendor_config(trackers, vendor_config.tracker_vendors);

    if (recording_config)
    {
        for (const auto& [tracker_ptr, name] : recording_config->tracker_names)
        {
            if (!tracker_in_list(trackers, tracker_ptr))
            {
                throw std::invalid_argument("DeviceIOSession: McapRecordingConfig references tracker '" + name +
                                            "' that is not in the trackers list");
            }
        }

        mcap_writer_ = std::make_unique<mcap::McapWriter>();
        mcap::McapWriterOptions options("teleop");
        options.compression = mcap::Compression::None;

        auto status = mcap_writer_->open(recording_config->filename, options);
        if (!status.ok())
        {
            throw std::runtime_error("DeviceIOSession: failed to open MCAP file '" + recording_config->filename +
                                     "': " + status.message);
        }
        std::cout << "DeviceIOSession: recording to " << recording_config->filename << std::endl;

        tracker_names = std::move(recording_config->tracker_names);
        recording_filename_ = recording_config->filename;
        embedded_media_filename_ = std::move(recording_config->embedded_media_filename);
    }

    LiveDeviceIOFactory factory(handles_, mcap_writer_.get(), tracker_names, vendor_config.tracker_vendors);

    for (const auto& tracker : trackers)
    {
        if (!tracker)
        {
            throw std::invalid_argument("DeviceIOSession: null tracker in trackers list");
        }
        tracker_impls_.emplace(tracker.get(), factory.create_tracker_impl(*tracker));
    }
}

DeviceIOSession::~DeviceIOSession()
{
    try
    {
        close();
    }
    catch (const std::exception& error)
    {
        // A destructor cannot report a recoverable error to the session caller.
        // Keep both source files for diagnosis rather than deleting evidence.
        std::cerr << "DeviceIOSession: failed to finalize embedded media MCAP: " << error.what() << std::endl;
    }
}

void DeviceIOSession::close()
{
    if (closed_)
        return;
    // Trackers own channel writers and must be destroyed before the final footer.
    tracker_impls_.clear();
    if (!mcap_writer_)
    {
        closed_ = true;
        return;
    }
    try
    {
        mcap_writer_->close();
        if (!embedded_media_filename_.empty())
            merge_embedded_media(recording_filename_, embedded_media_filename_);
        closed_ = true;
    }
    catch (...)
    {
        // Preserve source and fragment files for recovery, but do not retry a
        // partially completed merge from the destructor.
        closed_ = true;
        throw;
    }
}

std::vector<std::string> DeviceIOSession::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                                  const VendorConfig& vendor_config)
{
    // Validate here too, so an extension query rejects a bad vendor config just like construction.
    validate_vendor_config(trackers, vendor_config.tracker_vendors);
    return LiveDeviceIOFactory::get_required_extensions(trackers, vendor_config.tracker_vendors);
}

std::unique_ptr<DeviceIOSession> DeviceIOSession::run(const std::vector<std::shared_ptr<ITracker>>& trackers,
                                                      const OpenXRSessionHandles& handles,
                                                      std::optional<McapRecordingConfig> recording_config,
                                                      VendorConfig vendor_config)
{
    assert(handles.instance != XR_NULL_HANDLE && "OpenXR instance handle cannot be null");
    assert(handles.session != XR_NULL_HANDLE && "OpenXR session handle cannot be null");
    assert(handles.space != XR_NULL_HANDLE && "OpenXR space handle cannot be null");

    std::cout << "DeviceIOSession: Creating session with " << trackers.size() << " trackers" << std::endl;

    return std::unique_ptr<DeviceIOSession>(
        new DeviceIOSession(trackers, handles, std::move(recording_config), std::move(vendor_config)));
}

void DeviceIOSession::update()
{
    const int64_t monotonic_ns = os_monotonic_now_ns();

    for (auto& kv : tracker_impls_)
    {
        kv.second->update(monotonic_ns);
    }
}

} // namespace core
