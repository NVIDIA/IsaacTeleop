// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// A session whose trackers all work without OpenXR (the in-process keyboard) runs with null
// OpenXR handles, including MCAP recording; any tracker that needs OpenXR still requires them.

#include <catch2/catch_test_macros.hpp>
#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_session/replay_session.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <deviceio_trackers/keyboard_tracker.hpp>
#include <live_trackers/live_deviceio_factory.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/keyboard_generated.h>

#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#    include <process.h>
#    define GET_PID() _getpid()
#else
#    include <unistd.h>
#    define GET_PID() ::getpid()
#endif

namespace
{

constexpr uint16_t KEY_W = 17;
constexpr uint16_t KEY_K = 37;

std::string temp_mcap_path()
{
    static std::atomic<int> count{ 0 };
    const auto name = "test_openxr_free_" + std::to_string(GET_PID()) + "_" + std::to_string(count++) + ".mcap";
    return (std::filesystem::temp_directory_path() / name).string();
}

} // namespace

TEST_CASE("requires_openxr: keyboard needs none, OpenXR trackers do", "[unit][keyboard][openxr_free]")
{
    auto keyboard = std::make_shared<core::KeyboardTracker>();
    auto head = std::make_shared<core::HeadTracker>();

    CHECK_FALSE(core::DeviceIOSession::requires_openxr({ keyboard }));
    CHECK(core::DeviceIOSession::requires_openxr({ head }));
    CHECK(core::DeviceIOSession::requires_openxr({ keyboard, head }));
    CHECK_FALSE(core::LiveDeviceIOFactory::requires_openxr({ keyboard }));
}

TEST_CASE("DeviceIOSession: keyboard-only session runs without OpenXR handles", "[unit][keyboard][openxr_free]")
{
    auto keyboard = std::make_shared<core::KeyboardTracker>();
    auto session = core::DeviceIOSession::run({ keyboard }, core::OpenXRSessionHandles{});
    REQUIRE(session != nullptr);

    session->update();
    CHECK_FALSE(keyboard->get_data(*session)); // no provider attached yet

    auto provider = keyboard->create_provider("test");
    provider->key_down(KEY_W, 10);
    provider->tap(KEY_K, 20);
    session->update();

    const auto& data = keyboard->get_data(*session);
    REQUIRE(data);
    REQUIRE(data->pressed_keys()->size() == 1);
    CHECK(data->pressed_keys()->Get(0) == KEY_W);
    REQUIRE(data->events()->size() == 3);
    CHECK(data->events()->Get(1)->code() == KEY_K);
    CHECK(data->events()->Get(1)->action() == core::KeyAction_Press);
    CHECK(data->events()->Get(2)->action() == core::KeyAction_Release);
}

TEST_CASE("DeviceIOSession: null handles are rejected when a tracker needs OpenXR", "[unit][keyboard][openxr_free]")
{
    auto keyboard = std::make_shared<core::KeyboardTracker>();
    auto head = std::make_shared<core::HeadTracker>();

    CHECK_THROWS_AS(core::DeviceIOSession::run({ keyboard, head }, core::OpenXRSessionHandles{}), std::invalid_argument);
}

TEST_CASE("DeviceIOSession: keyboard records without OpenXR and replays", "[unit][keyboard][openxr_free]")
{
    const auto path = temp_mcap_path();
    struct Cleanup
    {
        std::string path;
        ~Cleanup()
        {
            std::error_code ec;
            std::filesystem::remove(path, ec);
        }
    } cleanup{ path };

    {
        auto keyboard = std::make_shared<core::KeyboardTracker>();
        auto provider = keyboard->create_provider("test");
        auto session = core::DeviceIOSession::run({ keyboard }, core::OpenXRSessionHandles{},
                                                  core::McapRecordingConfig{ path, { { keyboard.get(), "kb" } } });
        provider->key_down(KEY_W, 10);
        session->update();
        provider->key_up(KEY_W, 20);
        session->update();
    }

    core::KeyboardTracker replayed;
    auto replay = core::ReplaySession::run(core::McapReplayConfig{ path, { { &replayed, "kb" } } });

    replay->update();
    const auto& first = replayed.get_data(*replay);
    REQUIRE(first);
    REQUIRE(first->pressed_keys()->size() == 1);
    CHECK(first->pressed_keys()->Get(0) == KEY_W);

    replay->update();
    const auto& second = replayed.get_data(*replay);
    REQUIRE(second);
    CHECK((second->pressed_keys() == nullptr || second->pressed_keys()->size() == 0));
    REQUIRE(second->events()->size() == 1);
    CHECK(second->events()->Get(0)->action() == core::KeyAction_Release);
}
