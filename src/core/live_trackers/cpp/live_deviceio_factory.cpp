// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/live_trackers/live_deviceio_factory.hpp"

#include "live_controller_tracker_impl.hpp"
#include "live_frame_metadata_tracker_oak_impl.hpp"
#include "live_full_body_tracker_pico_impl.hpp"
#include "live_generic_3axis_pedal_tracker_impl.hpp"
#include "live_hand_tracker_impl.hpp"
#include "live_haptic_command_reader_tracker_impl.hpp"
#include "live_head_tracker_impl.hpp"
#include "live_joint_state_tracker_impl.hpp"
#include "live_message_channel_tracker_impl.hpp"
#include "live_oglo_tactile_tracker_impl.hpp"
#include "live_se3_tracker_impl.hpp"
#include "live_tensor_push_tracker_impl.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <deviceio_trackers/full_body_tracker.hpp>
#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/haptic_command_reader_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <deviceio_trackers/joint_state_tracker.hpp>
#include <deviceio_trackers/message_channel_tracker.hpp>
#include <deviceio_trackers/oglo_tactile_tracker.hpp>
#include <deviceio_trackers/se3_tracker.hpp>
#include <deviceio_trackers/tensor_push_tracker.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <cassert>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

namespace core
{

namespace
{

template <typename TrackerT, typename ImplT>
bool try_add_extensions(const ITracker& tracker, std::set<std::string>& out)
{
    if (dynamic_cast<const TrackerT*>(&tracker))
    {
        for (const auto& ext : ImplT::required_extensions())
            out.insert(ext);
        return true;
    }
    return false;
}

std::unique_ptr<ITrackerImpl> try_create_head_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HeadTracker*>(&tracker);
    return typed ? factory.create_head_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_hand_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HandTracker*>(&tracker);
    return typed ? factory.create_hand_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_controller_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const ControllerTracker*>(&tracker);
    return typed ? factory.create_controller_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_message_channel_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const MessageChannelTracker*>(&tracker);
    return typed ? factory.create_message_channel_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_generic_pedal_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const Generic3AxisPedalTracker*>(&tracker);
    return typed ? factory.create_generic_3axis_pedal_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_tensor_push_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const TensorPushTracker*>(&tracker);
    return typed ? factory.create_tensor_push_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_haptic_command_reader_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HapticCommandReaderTracker*>(&tracker);
    return typed ? factory.create_haptic_command_reader_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_joint_state_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const JointStateTracker*>(&tracker);
    return typed ? factory.create_joint_state_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_se3_tracker_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const Se3Tracker*>(&tracker);
    return typed ? factory.create_se3_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_oak_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const FrameMetadataTrackerOak*>(&tracker);
    return typed ? factory.create_frame_metadata_tracker_oak_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_oglo_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const OgloTactileTracker*>(&tracker);
    return typed ? factory.create_oglo_tactile_tracker_impl(typed) : nullptr;
}

using CollectExtensionsFn = bool (*)(const ITracker&, std::set<std::string>&);
using TryCreateFn = std::unique_ptr<ITrackerImpl> (*)(LiveDeviceIOFactory&, const ITracker&);

struct TrackerDispatchEntry
{
    CollectExtensionsFn collect_extensions;
    TryCreateFn try_create;
};

// Shared tracker dispatch table for both extension collection and impl creation.
// Vendored trackers (FullBodyTracker) are intentionally absent here: they are
// routed through the vendor registry (k_full_body_vendors) ahead of this table
// in both get_required_extensions() and create_tracker_impl().
inline const TrackerDispatchEntry k_tracker_dispatch[] = {
    { &try_add_extensions<HeadTracker, LiveHeadTrackerImpl>, &try_create_head_impl },
    { &try_add_extensions<HandTracker, LiveHandTrackerImpl>, &try_create_hand_impl },
    { &try_add_extensions<ControllerTracker, LiveControllerTrackerImpl>, &try_create_controller_impl },
    { &try_add_extensions<MessageChannelTracker, LiveMessageChannelTrackerImpl>, &try_create_message_channel_impl },
    { &try_add_extensions<Generic3AxisPedalTracker, LiveGeneric3AxisPedalTrackerImpl>, &try_create_generic_pedal_impl },
    { &try_add_extensions<TensorPushTracker, LiveTensorPushTrackerImpl>, &try_create_tensor_push_impl },
    { &try_add_extensions<HapticCommandReaderTracker, LiveHapticCommandReaderTrackerImpl>,
      &try_create_haptic_command_reader_impl },
    { &try_add_extensions<JointStateTracker, LiveJointStateTrackerImpl>, &try_create_joint_state_impl },
    { &try_add_extensions<Se3Tracker, LiveSe3TrackerImpl>, &try_create_se3_tracker_impl },
    { &try_add_extensions<FrameMetadataTrackerOak, LiveFrameMetadataTrackerOakImpl>, &try_create_oak_impl },
    { &try_add_extensions<OgloTactileTracker, LiveOgloTactileTrackerImpl>, &try_create_oglo_impl },
};

// ---------------------------------------------------------------------------
// Full-body vendor registry
//
// A vendor-agnostic FullBodyTracker is routed to a concrete live impl by a
// string vendor id (e.g. "body.pico-xr"). New pre-built plugin vendors are added
// by registering another entry here; the tracker marker never changes. The
// params bag carries vendor-specific settings (unused for the native PICO impl).
// ---------------------------------------------------------------------------

using VendorParams = std::map<std::string, std::string>;

struct FullBodyVendorEntry
{
    std::vector<std::string> (*required_extensions)();
    std::unique_ptr<ITrackerImpl> (*build)(LiveDeviceIOFactory&, const FullBodyTracker&, const VendorParams&);
};

std::unique_ptr<ITrackerImpl> build_full_body_pico_xr(LiveDeviceIOFactory& factory,
                                                      const FullBodyTracker& tracker,
                                                      const VendorParams& /*params*/)
{
    return factory.create_full_body_tracker_pico_impl(&tracker);
}

const std::unordered_map<std::string_view, FullBodyVendorEntry> k_full_body_vendors = {
    { "body.pico-xr", { &LiveFullBodyTrackerPicoImpl::required_extensions, &build_full_body_pico_xr } },
};

const FullBodyVendorEntry& resolve_full_body_vendor(std::string_view id)
{
    auto it = k_full_body_vendors.find(id);
    if (it == k_full_body_vendors.end())
    {
        throw std::invalid_argument("LiveDeviceIOFactory: unknown full-body vendor id '" + std::string(id) + "'");
    }
    return it->second;
}

// Find a tracker's vendor selection in the config, or nullptr when unlisted.
const TrackerVendor* find_full_body_vendor(const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors,
                                           const ITracker* tracker)
{
    for (const auto& [ptr, vendor] : tracker_vendors)
    {
        if (ptr == tracker)
            return &vendor;
    }
    return nullptr;
}

// Resolve the registry entry for a full-body vendor selection (nullptr -> default vendor id).
const FullBodyVendorEntry& resolve_full_body_entry(const TrackerVendor* selected)
{
    return resolve_full_body_vendor(selected ? std::string_view(selected->id) : FullBodyTracker::DEFAULT_VENDOR_ID);
}

// Validate per-tracker vendor selections independently of the tracker list:
// reject selections on tracker types that do not support vendors, unknown vendor
// ids, and duplicate entries. Shared by the factory constructor and
// get_required_extensions() so both reject identical vendor configurations.
// (Presence in the session's tracker list is checked by the callers that hold
// that list.)
void validate_vendor_selections(const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors)
{
    std::unordered_set<const ITracker*> seen;
    for (const auto& [tracker, vendor] : tracker_vendors)
    {
        // Only vendored tracker types accept a vendor selection; reject any other so a
        // misassigned (silently-ignored) selection surfaces as an error.
        if (!dynamic_cast<const FullBodyTracker*>(tracker))
        {
            throw std::invalid_argument("LiveDeviceIOFactory: vendor selection '" + vendor.id +
                                        "' provided for a tracker that does not support vendors");
        }
        // Reject unknown vendor ids up front rather than when the impl is built.
        resolve_full_body_vendor(vendor.id);

        if (!seen.insert(tracker).second)
        {
            throw std::invalid_argument("LiveDeviceIOFactory: duplicate vendor selection for a tracker (vendor id '" +
                                        vendor.id + "')");
        }
    }
}

} // namespace

std::vector<std::string> LiveDeviceIOFactory::get_required_extensions(
    const std::vector<std::shared_ptr<ITracker>>& trackers,
    const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors)
{
    std::set<std::string> all;

    // Validate the complete vendor mapping before resolving extensions so that
    // extension discovery and session construction accept identical configs.
    // Mirror the session path's order: first reject selections for trackers
    // absent from the list (as the DeviceIOSession constructor does), then the
    // tracker-list-independent checks (unsupported type, unknown vendor id,
    // duplicates) shared with the factory constructor.
    if (!tracker_vendors.empty())
    {
        std::unordered_set<const ITracker*> known;
        known.reserve(trackers.size());
        for (const auto& tracker : trackers)
            known.insert(tracker.get());

        for (const auto& [tracker, vendor] : tracker_vendors)
        {
            if (known.find(tracker) == known.end())
            {
                throw std::invalid_argument("LiveDeviceIOFactory::get_required_extensions: vendor selection '" +
                                            vendor.id + "' references a tracker that is not in the trackers list");
            }
        }
    }
    validate_vendor_selections(tracker_vendors);

    // DeviceIOSession always owns an XrTimeConverter; match session requirements even with zero trackers.
    for (const auto& ext : XrTimeConverter::get_required_extensions())
        all.insert(ext);

    for (const auto& tracker : trackers)
    {
        if (!tracker)
            throw std::invalid_argument("LiveDeviceIOFactory: null tracker in trackers list");

        // Vendored trackers resolve their extensions through the vendor registry.
        if (dynamic_cast<const FullBodyTracker*>(tracker.get()))
        {
            const TrackerVendor* selected = find_full_body_vendor(tracker_vendors, tracker.get());
            for (const auto& ext : resolve_full_body_entry(selected).required_extensions())
                all.insert(ext);
            continue;
        }

        bool matched = false;
        for (const auto& dispatch : k_tracker_dispatch)
        {
            if (dispatch.collect_extensions(*tracker, all))
            {
                matched = true;
                break;
            }
        }

        if (!matched)
        {
            throw std::invalid_argument("LiveDeviceIOFactory::get_required_extensions: unsupported tracker type '" +
                                        std::string(tracker->get_name()) + "'");
        }
    }

    return { all.begin(), all.end() };
}

LiveDeviceIOFactory::LiveDeviceIOFactory(const OpenXRSessionHandles& handles,
                                         mcap::McapWriter* writer,
                                         const std::vector<std::pair<const ITracker*, std::string>>& tracker_names,
                                         const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors)
    : handles_(handles), writer_(writer)
{
    for (const auto& [tracker, name] : tracker_names)
    {
        auto [it, inserted] = name_map_.emplace(tracker, name);
        if (!inserted)
        {
            throw std::invalid_argument("LiveDeviceIOFactory: duplicate tracker pointer for channel name '" + name +
                                        "' (already mapped as '" + it->second + "')");
        }
    }

    // Reject unsupported tracker types, unknown vendor ids, and duplicate entries
    // using the same routine as get_required_extensions() so session construction
    // and extension discovery accept identical vendor configurations. (Presence in
    // the session's tracker list is validated by the DeviceIOSession constructor.)
    validate_vendor_selections(tracker_vendors);
    for (const auto& [tracker, vendor] : tracker_vendors)
    {
        vendor_map_.emplace(tracker, vendor);
    }
}

std::unique_ptr<ITrackerImpl> LiveDeviceIOFactory::create_tracker_impl(const ITracker& tracker)
{
    // Vendored trackers resolve their concrete impl through the vendor registry.
    if (const auto* full_body = dynamic_cast<const FullBodyTracker*>(&tracker))
    {
        auto it = vendor_map_.find(&tracker);
        const TrackerVendor* selected = (it != vendor_map_.end()) ? &it->second : nullptr;
        static const VendorParams k_no_params;
        const VendorParams& params = selected ? selected->params : k_no_params;
        return resolve_full_body_entry(selected).build(*this, *full_body, params);
    }

    for (const auto& dispatch : k_tracker_dispatch)
    {
        if (std::unique_ptr<ITrackerImpl> impl = dispatch.try_create(*this, tracker))
        {
            return impl;
        }
    }
    throw std::invalid_argument("LiveDeviceIOFactory::create_tracker_impl: unsupported tracker type '" +
                                std::string(tracker.get_name()) + "'");
}

bool LiveDeviceIOFactory::should_record(const ITracker* tracker) const
{
    return writer_ && name_map_.count(tracker);
}

std::string_view LiveDeviceIOFactory::get_name(const ITracker* tracker) const
{
    auto it = name_map_.find(tracker);
    assert(it != name_map_.end() && "get_name called for tracker not in name_map_ (call should_record first)");
    return it->second;
}

std::unique_ptr<IHeadTrackerImpl> LiveDeviceIOFactory::create_head_tracker_impl(const HeadTracker* tracker)
{
    std::unique_ptr<HeadMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveHeadTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveHeadTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<IHandTrackerImpl> LiveDeviceIOFactory::create_hand_tracker_impl(const HandTracker* tracker)
{
    std::unique_ptr<HandMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveHandTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveHandTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<IControllerTrackerImpl> LiveDeviceIOFactory::create_controller_tracker_impl(const ControllerTracker* tracker)
{
    std::unique_ptr<ControllerMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveControllerTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveControllerTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<IMessageChannelTrackerImpl> LiveDeviceIOFactory::create_message_channel_tracker_impl(
    const MessageChannelTracker* tracker)
{
    std::unique_ptr<MessageChannelMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveMessageChannelTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveMessageChannelTrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<IFullBodyTrackerImpl> LiveDeviceIOFactory::create_full_body_tracker_pico_impl(const FullBodyTracker* tracker)
{
    std::unique_ptr<FullBodyMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveFullBodyTrackerPicoImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveFullBodyTrackerPicoImpl>(handles_, std::move(channels));
}

std::unique_ptr<IGeneric3AxisPedalTrackerImpl> LiveDeviceIOFactory::create_generic_3axis_pedal_tracker_impl(
    const Generic3AxisPedalTracker* tracker)
{
    std::unique_ptr<PedalMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveGeneric3AxisPedalTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveGeneric3AxisPedalTrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<IOgloTactileTrackerImpl> LiveDeviceIOFactory::create_oglo_tactile_tracker_impl(
    const OgloTactileTracker* tracker)
{
    std::unique_ptr<OgloMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveOgloTactileTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveOgloTactileTrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<ITensorPushTrackerImpl> LiveDeviceIOFactory::create_tensor_push_tracker_impl(const TensorPushTracker* tracker)
{
    return std::make_unique<LiveTensorPushTrackerImpl>(handles_, tracker);
}

std::unique_ptr<IHapticCommandReaderTrackerImpl> LiveDeviceIOFactory::create_haptic_command_reader_tracker_impl(
    const HapticCommandReaderTracker* tracker)
{
    return std::make_unique<LiveHapticCommandReaderTrackerImpl>(handles_, tracker);
}

std::unique_ptr<IJointStateTrackerImpl> LiveDeviceIOFactory::create_joint_state_tracker_impl(const JointStateTracker* tracker)
{
    std::unique_ptr<JointStateMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveJointStateTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveJointStateTrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<ISe3TrackerImpl> LiveDeviceIOFactory::create_se3_tracker_impl(const Se3Tracker* tracker)
{
    std::unique_ptr<Se3TrackerMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveSe3TrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveSe3TrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<IFrameMetadataTrackerOakImpl> LiveDeviceIOFactory::create_frame_metadata_tracker_oak_impl(
    const FrameMetadataTrackerOak* tracker)
{
    std::unique_ptr<OakMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveFrameMetadataTrackerOakImpl::create_mcap_channels(*writer_, get_name(tracker), tracker);
    }
    return std::make_unique<LiveFrameMetadataTrackerOakImpl>(handles_, tracker, std::move(channels));
}

} // namespace core
