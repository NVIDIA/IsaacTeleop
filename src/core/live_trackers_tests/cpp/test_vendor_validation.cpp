// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for vendor-selection validation. Validation is owned by DeviceIOSession
// (the single gatekeeper): it runs the tracker-list presence check itself and delegates
// the dispatch-driven vendor-validity checks to core::validate_vendor_selections(). The
// live factory assumes a validated config.
//
// Most outcomes are exercised through DeviceIOSession::get_required_extensions(), the
// public entry point plugins call; it validates the vendor config before resolving
// extensions and needs no OpenXR handles.
//
// Outcomes covered:
//   1. accepted   - a vendored tracker with a known vendor id (and the default,
//                   no-selection, path) resolves and returns extensions.
//   2. rejected   - a vendor selection on a non-vendored tracker type.
//   3. rejected   - an unknown vendor id.
//   4. accepted or rejected - vendor params according to the selected vendor's contract.
//   5. rejected   - a duplicate selection for the same tracker.
//   6. rejected   - a selection referencing a tracker absent from the list.
// Plus a direct unit test of the list-independent primitive
// core::validate_vendor_selections().

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <deviceio_base/tracker.hpp>
#include <deviceio_base/tracker_vendor.hpp>
#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/frame_metadata_tracker_orbbec.hpp>
#include <deviceio_trackers/full_body_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <deviceio_trackers/orbbec_ego_trackers.hpp>
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

// Runs DeviceIOSession::get_required_extensions and returns the thrown
// std::invalid_argument message, or an empty string when it does not throw.
std::string vendor_validation_error(const TrackerList& trackers, const VendorList& vendors)
{
    try
    {
        core::DeviceIOSession::get_required_extensions(trackers, core::VendorConfig{ vendors });
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
        const auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
        REQUIRE(contains(extensions, "XR_BD_body_tracking"));
    }

    SECTION("explicitly naming the default vendor is accepted and resolves the same way")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.pico-xr" } } };
        std::vector<std::string> extensions;
        REQUIRE_NOTHROW(extensions =
                            core::DeviceIOSession::get_required_extensions(trackers, core::VendorConfig{ vendors }));
        REQUIRE(contains(extensions, "XR_BD_body_tracking"));
    }

    SECTION("Noitom vendor selects tensor data extensions")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.noitom" } } };
        const auto extensions = core::DeviceIOSession::get_required_extensions(trackers, core::VendorConfig{ vendors });
        REQUIRE(contains(extensions, "XR_NVX1_tensor_data"));
        REQUIRE_FALSE(contains(extensions, "XR_BD_body_tracking"));
    }

    SECTION("Noitom vendor accepts collection and sample-size parameters")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.noitom",
                                                               { { "collection_id", "custom_noitom" },
                                                                 { "max_flatbuffer_size", "32768" } } } } };
        REQUIRE_NOTHROW(core::DeviceIOSession::get_required_extensions(trackers, core::VendorConfig{ vendors }));
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

    SECTION("an unsupported Noitom vendor parameter is rejected")
    {
        VendorList vendors{
            { body.get(), core::TrackerVendor{ "body.noitom", { { "unsupported", "value" } } } },
        };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("does not support parameter"));
    }

    SECTION("an invalid Noitom max flatbuffer size is rejected")
    {
        VendorList vendors{
            { body.get(), core::TrackerVendor{ "body.noitom", { { "max_flatbuffer_size", "0" } } } },
        };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("must be a positive integer"));
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
        // Presence check owned by DeviceIOSession: the stray tracker is validated
        // but never added to the session's tracker list.
        auto stray = std::make_shared<core::FullBodyTracker>();
        VendorList vendors{ { stray.get(), core::TrackerVendor{ "body.pico-xr" } } };
        REQUIRE_THAT(vendor_validation_error(trackers, vendors), ContainsSubstring("not in the trackers list"));
    }
}

// This primitive is list-independent: it runs the dispatch-driven checks with no tracker
// list (presence is the caller's responsibility) and is what the session delegates to.
TEST_CASE("vendor validation: validate_vendor_selections rejects an invalid selection directly", "[live_trackers][vendor]")
{
    auto body = std::make_shared<core::FullBodyTracker>();

    SECTION("a valid selection is accepted")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.pico-xr" } } };
        REQUIRE_NOTHROW(core::validate_vendor_selections(vendors));
    }

    SECTION("an invalid selection is rejected")
    {
        VendorList vendors{ { body.get(), core::TrackerVendor{ "body.does-not-exist" } } };
        REQUIRE_THROWS_AS(core::validate_vendor_selections(vendors), std::invalid_argument);
    }
}

TEST_CASE("Orbbec frame metadata tracker requires the schema tensor extensions", "[live_trackers][orbbec]")
{
    auto tracker = std::make_shared<core::FrameMetadataTrackerOrbbec>(
        "orbbec_ego", std::vector{ core::OrbbecCameraStream_ColorLeft, core::OrbbecCameraStream_ColorRight });
    const auto extensions = core::DeviceIOSession::get_required_extensions({ tracker });
    // The host tracker consumes tensor data. The separate camera plugin owns
    // SchemaPusher and therefore owns the push-tensor extension requirement.
    REQUIRE(contains(extensions, "XR_NVX1_tensor_data"));
    REQUIRE_FALSE(contains(extensions, "XR_NVX1_push_tensor"));
}

TEST_CASE("Orbbec frame metadata tracker validates stream configuration", "[live_trackers][orbbec]")
{
    REQUIRE_THROWS_AS(core::FrameMetadataTrackerOrbbec("orbbec_ego", {}), std::invalid_argument);
    REQUIRE_THROWS_AS(
        core::FrameMetadataTrackerOrbbec("", { core::OrbbecCameraStream_ColorLeft }), std::invalid_argument);
    REQUIRE_THROWS_AS(core::FrameMetadataTrackerOrbbec(
                          "orbbec_ego", { core::OrbbecCameraStream_ColorLeft, core::OrbbecCameraStream_ColorLeft }),
                      std::invalid_argument);
    REQUIRE_THROWS_AS(core::FrameMetadataTrackerOrbbec("orbbec_ego", { core::OrbbecCameraStream_ColorLeft }, 0),
                      std::invalid_argument);
}

TEST_CASE("Orbbec Ego auxiliary trackers require schema extensions and validate input", "[live_trackers][orbbec]")
{
    auto imu = std::make_shared<core::OrbbecImuTracker>("ego");
    auto audio = std::make_shared<core::OrbbecAudioTracker>("ego");
    auto calibration = std::make_shared<core::OrbbecCalibrationTracker>("ego");
    auto state = std::make_shared<core::OrbbecDeviceStateTracker>("ego");
    const auto extensions = core::DeviceIOSession::get_required_extensions({ imu, audio, calibration, state });
    REQUIRE(contains(extensions, "XR_NVX1_tensor_data"));
    REQUIRE_THROWS_AS(core::OrbbecImuTracker("", {}), std::invalid_argument);
    REQUIRE_THROWS_AS(core::OrbbecImuTracker("ego", { core::OrbbecImuSensor_Accel, core::OrbbecImuSensor_Accel }),
                      std::invalid_argument);
    REQUIRE_THROWS_AS(core::OrbbecAudioTracker("ego", 0), std::invalid_argument);
}
