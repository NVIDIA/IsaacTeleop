// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the live factory's vendor-selection validation
// (validate_vendor_selections). That routine has internal linkage, so its
// outcomes are surfaced through the public static entry point
// LiveDeviceIOFactory::get_required_extensions(), which validates the vendor
// config before resolving extensions and needs no OpenXR handles.
//
// Outcomes covered:
//   1. accepted   - a vendored tracker with a known vendor id (and the default,
//                   no-selection, path) resolves and returns extensions.
//   2. rejected   - a vendor selection on a non-vendored tracker type.
//   3. rejected   - an unknown vendor id.
//   4. rejected   - non-empty vendor params (no consumer reads them yet).
//   5. rejected   - a duplicate selection for the same tracker.
// Plus the sibling presence check in get_required_extensions():
//   6. rejected   - a selection referencing a tracker absent from the list.

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <deviceio_base/tracker.hpp>
#include <deviceio_base/tracker_vendor.hpp>
#include <deviceio_trackers/full_body_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <live_trackers/live_deviceio_factory.hpp>

#include <algorithm>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using Catch::Matchers::ContainsSubstring;

namespace
{

using TrackerList = std::vector<std::shared_ptr<core::ITracker>>;
using VendorList = std::vector<std::pair<const core::ITracker*, core::TrackerVendor>>;

// Runs get_required_extensions and returns the thrown std::invalid_argument
// message, or an empty string when it does not throw.
std::string vendor_validation_error(const TrackerList& trackers, const VendorList& vendors)
{
    try
    {
        core::LiveDeviceIOFactory::get_required_extensions(trackers, vendors);
        return {};
    }
    catch (const std::invalid_argument& e)
    {
        return e.what();
    }
}

bool contains(const std::vector<std::string>& haystack, const std::string& needle)
{
    return std::find(haystack.begin(), haystack.end(), needle) != haystack.end();
}

} // namespace

TEST_CASE("vendor validation: accepted configurations resolve extensions", "[live_trackers][vendor]")
{
    auto body = std::make_shared<core::FullBodyTracker>();
    TrackerList trackers{ body };

    SECTION("no vendor config falls back to the default vendor")
    {
        // Empty vendor config -> default vendor (body.pico-xr) is selected.
        const auto extensions = core::LiveDeviceIOFactory::get_required_extensions(trackers);
        REQUIRE(contains(extensions, "XR_BD_body_tracking"));
    }

    SECTION("explicitly naming the default vendor is accepted and resolves the same way")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.pico-xr" } } };
        std::vector<std::string> extensions;
        REQUIRE_NOTHROW(extensions = core::LiveDeviceIOFactory::get_required_extensions(trackers, vendors));
        REQUIRE(contains(extensions, "XR_BD_body_tracking"));
    }
}

TEST_CASE("vendor validation: invalid configurations are rejected", "[live_trackers][vendor]")
{
    auto body = std::make_shared<core::FullBodyTracker>();
    auto head = std::make_shared<core::HeadTracker>();
    TrackerList trackers{ body, head };

    SECTION("a vendor selection on a non-vendored tracker type is rejected")
    {
        VendorList vendors{ { head.get(), core::TrackerVendor{ "body.pico-xr" } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("does not support vendors"));
    }

    SECTION("an unknown vendor id is rejected")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.does-not-exist" } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("unknown vendor id"));
    }

    SECTION("an empty vendor id is rejected as unknown (not silently matched to the sentinel rows)")
    {
        // A default-constructed / empty TrackerVendor id must not match the empty
        // vendor_id sentinel carried by non-vendored dispatch rows.
        VendorList vendors{ { body.get(), core::TrackerVendor{ "" } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("unknown vendor id"));
    }

    SECTION("a non-empty vendor params map is rejected while no vendor consumes it")
    {
        // params is bound and reserved, but no impl reads it yet; a non-empty map
        // must be rejected rather than silently dropped.
        VendorList vendors{ { body.get(),
                              core::TrackerVendor{ "body.pico-xr", { { "max_flatbuffer_size", "16384" } } } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("params are not supported"));
    }

    SECTION("a duplicate selection for the same tracker is rejected")
    {
        VendorList vendors{
            { body.get(), core::TrackerVendor{ "body.pico-xr" } },
            { body.get(), core::TrackerVendor{ "body.pico-xr" } },
        };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("duplicate vendor selection"));
    }

    SECTION("a selection referencing a tracker absent from the list is rejected")
    {
        // Sibling presence check in get_required_extensions(): the stray tracker
        // is validated but never added to the session's tracker list.
        auto stray = std::make_shared<core::FullBodyTracker>();
        VendorList vendors{ { stray.get(), core::TrackerVendor{ "body.pico-xr" } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("not in the trackers list"));
    }
}
