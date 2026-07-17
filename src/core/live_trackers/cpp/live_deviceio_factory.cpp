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

#include <algorithm>
#include <cassert>
#include <optional>
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

std::unique_ptr<ITrackerImpl> try_create_full_body_pico_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const FullBodyTracker*>(&tracker);
    return typed ? factory.create_full_body_tracker_pico_impl(typed) : nullptr;
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
    // Vendor routing (last so single-vendor rows can omit them): a default-initialized row is a
    // type's sole default vendor; multi-vendor types set vendor_id per row and clear is_default
    // on the non-default rows.
    std::string_view vendor_id = {};
    bool is_default = true;
};

// One row per (tracker type, vendor). A tracker type may have several vendor rows; is_default marks
// the row chosen when no vendor is selected. Extension discovery and impl creation both scan this
// table: keep rows whose vendor id matches the selection (or is_default when unselected), then the
// row's type-checked thunk builds the concrete impl.
inline const TrackerDispatchEntry k_tracker_dispatch[] = {
    { &try_add_extensions<HeadTracker, LiveHeadTrackerImpl>, &try_create_head_impl },
    { &try_add_extensions<HandTracker, LiveHandTrackerImpl>, &try_create_hand_impl },
    { &try_add_extensions<ControllerTracker, LiveControllerTrackerImpl>, &try_create_controller_impl },
    { &try_add_extensions<MessageChannelTracker, LiveMessageChannelTrackerImpl>, &try_create_message_channel_impl },
    { &try_add_extensions<FullBodyTracker, LiveFullBodyTrackerPicoImpl>, &try_create_full_body_pico_impl, "body.pico-xr" },
    { &try_add_extensions<Generic3AxisPedalTracker, LiveGeneric3AxisPedalTrackerImpl>, &try_create_generic_pedal_impl },
    { &try_add_extensions<TensorPushTracker, LiveTensorPushTrackerImpl>, &try_create_tensor_push_impl },
    { &try_add_extensions<HapticCommandReaderTracker, LiveHapticCommandReaderTrackerImpl>,
      &try_create_haptic_command_reader_impl },
    { &try_add_extensions<JointStateTracker, LiveJointStateTrackerImpl>, &try_create_joint_state_impl },
    { &try_add_extensions<Se3Tracker, LiveSe3TrackerImpl>, &try_create_se3_tracker_impl },
    { &try_add_extensions<FrameMetadataTrackerOak, LiveFrameMetadataTrackerOakImpl>, &try_create_oak_impl },
    { &try_add_extensions<OgloTactileTracker, LiveOgloTactileTrackerImpl>, &try_create_oglo_impl },
};

// Find a tracker's vendor selection in the config, or nullptr when unlisted.
const TrackerVendor* find_tracker_vendor(const std::vector<std::pair<const ITracker*, TrackerVendor>>& tracker_vendors,
                                         const ITracker* tracker)
{
    for (const auto& [ptr, vendor] : tracker_vendors)
    {
        if (ptr == tracker)
            return &vendor;
    }
    return nullptr;
}

// True when a dispatch row is the one selected for a tracker: the chosen vendor id, or the
// type's default row when no vendor is selected.
bool row_selected(const TrackerDispatchEntry& row, const TrackerVendor* selected)
{
    return selected ? (row.vendor_id == selected->id) : row.is_default;
}

// No dispatch row produced an impl for a tracker (and its selected vendor); report why.
[[noreturn]] void throw_unresolved_tracker(const char* context, const ITracker& tracker, const TrackerVendor* selected)
{
    if (selected)
    {
        throw std::invalid_argument(std::string(context) + ": no live vendor '" + selected->id + "' for tracker '" +
                                    std::string(tracker.get_name()) + "'");
    }
    throw std::invalid_argument(std::string(context) + ": unsupported tracker type '" +
                                std::string(tracker.get_name()) + "'");
}

// True when a dispatch row offers this vendor id, i.e. it names a live vendor a tracker can select.
bool dispatch_has_vendor(std::string_view vendor_id)
{
    // An empty id is the non-vendored-row sentinel (vendor_id = {}), never a selectable
    // vendor. Reject it here so an empty TrackerVendor id is reported up front as an
    // unknown vendor id instead of matching those sentinel rows and failing later.
    if (vendor_id.empty())
        return false;
    for (const auto& row : k_tracker_dispatch)
    {
        if (row.vendor_id == vendor_id)
            return true;
    }
    return false;
}

// True when a tracker's type has at least one vendored dispatch row (a row with a
// non-empty vendor id). Derived from the table, not a hardcoded type: adding a
// vendored row for a new tracker type makes that type vendor-selectable here with
// no other change. collect_extensions doubles as the row's type probe -- it returns
// true only for a tracker of the row's type (the scratch extensions it collects on
// a match are discarded). Null is treated as unsupported.
bool tracker_supports_vendors(const ITracker* tracker)
{
    if (!tracker)
        return false;
    std::set<std::string> scratch;
    for (const auto& row : k_tracker_dispatch)
    {
        if (!row.vendor_id.empty() && row.collect_extensions(*tracker, scratch))
            return true;
    }
    return false;
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
        if (!tracker_supports_vendors(tracker))
        {
            throw std::invalid_argument("LiveDeviceIOFactory: vendor selection '" + vendor.id +
                                        "' provided for a tracker that does not support vendors");
        }
        // Reject unknown vendor ids up front rather than when the impl is built.
        if (!dispatch_has_vendor(vendor.id))
        {
            throw std::invalid_argument("LiveDeviceIOFactory: unknown vendor id '" + vendor.id + "'");
        }

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
    // Reject out-of-list selections first (matching the DeviceIOSession
    // constructor's order), then the list-independent checks (unsupported type,
    // unknown vendor id, duplicates) shared with the factory constructor.
    for (const auto& [tracker, vendor] : tracker_vendors)
    {
        const bool in_list =
            std::any_of(trackers.begin(), trackers.end(), [&](const auto& t) { return t.get() == tracker; });
        if (!in_list)
        {
            throw std::invalid_argument("LiveDeviceIOFactory::get_required_extensions: vendor selection '" + vendor.id +
                                        "' references a tracker that is not in the trackers list");
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

        const TrackerVendor* selected = find_tracker_vendor(tracker_vendors, tracker.get());

        bool matched = false;
        for (const auto& dispatch : k_tracker_dispatch)
        {
            if (!row_selected(dispatch, selected))
                continue;
            if (dispatch.collect_extensions(*tracker, all))
            {
                matched = true;
                break;
            }
        }

        if (!matched)
            throw_unresolved_tracker("LiveDeviceIOFactory::get_required_extensions", *tracker, selected);
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
        TrackerData& data = tracker_data_[tracker];
        if (data.name.has_value())
        {
            throw std::invalid_argument("LiveDeviceIOFactory: duplicate tracker pointer for channel name '" + name +
                                        "' (already mapped as '" + *data.name + "')");
        }
        data.name = name;
    }

    // Reject unsupported tracker types, unknown vendor ids, and duplicate entries
    // using the same routine as get_required_extensions() so session construction
    // and extension discovery accept identical vendor configurations. (Presence in
    // the session's tracker list is validated by the DeviceIOSession constructor.)
    validate_vendor_selections(tracker_vendors);
    for (const auto& [tracker, vendor] : tracker_vendors)
    {
        tracker_data_[tracker].vendor = vendor;
    }
}

std::unique_ptr<ITrackerImpl> LiveDeviceIOFactory::create_tracker_impl(const ITracker& tracker)
{
    const TrackerVendor* selected = find_vendor(&tracker);

    for (const auto& dispatch : k_tracker_dispatch)
    {
        if (!row_selected(dispatch, selected))
            continue;
        if (std::unique_ptr<ITrackerImpl> impl = dispatch.try_create(*this, tracker))
        {
            return impl;
        }
    }
    throw_unresolved_tracker("LiveDeviceIOFactory::create_tracker_impl", tracker, selected);
}

bool LiveDeviceIOFactory::should_record(const ITracker* tracker) const
{
    auto it = tracker_data_.find(tracker);
    return writer_ && it != tracker_data_.end() && it->second.name.has_value();
}

std::string_view LiveDeviceIOFactory::get_name(const ITracker* tracker) const
{
    auto it = tracker_data_.find(tracker);
    assert(it != tracker_data_.end() && it->second.name.has_value() &&
           "get_name called for tracker without a channel name (call should_record first)");
    return *it->second.name;
}

const TrackerVendor* LiveDeviceIOFactory::find_vendor(const ITracker* tracker) const
{
    auto it = tracker_data_.find(tracker);
    return (it != tracker_data_.end() && it->second.vendor) ? &*it->second.vendor : nullptr;
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
