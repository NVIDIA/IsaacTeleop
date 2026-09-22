// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the in-process keyboard: provider transitions, per-provider focus release,
// the multi-provider merge, and the per-frame drain the live impl publishes.

#include <catch2/catch_test_macros.hpp>
#include <deviceio_trackers/keyboard_tracker.hpp>

#include <cstdint>
#include <string>
#include <thread>
#include <vector>

namespace
{

constexpr uint16_t KEY_W = 17;
constexpr uint16_t KEY_A = 30;
constexpr uint16_t KEY_K = 37;

std::vector<uint16_t> event_codes(const core::KeyboardInputState::Snapshot& snapshot, bool pressed)
{
    std::vector<uint16_t> codes;
    for (const auto& event : snapshot.events)
    {
        if (event.pressed == pressed)
        {
            codes.push_back(event.code);
        }
    }
    return codes;
}

} // namespace

TEST_CASE("KeyboardInputState: no provider drains empty", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    const auto snapshot = tracker.input_state()->drain();

    CHECK(snapshot.provider_count == 0);
    CHECK(snapshot.pressed_keys.empty());
    CHECK(snapshot.events.empty());
}

TEST_CASE("KeyboardProvider: held keys and ordered events, autorepeat ignored", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    auto provider = tracker.create_provider("window");

    CHECK(provider->key_down(KEY_W, 100));
    CHECK_FALSE(provider->key_down(KEY_W, 110)); // autorepeat
    CHECK(provider->key_down(std::string_view("KeyA"), 120));
    CHECK_FALSE(provider->key_down(std::string_view("NotAKey")));

    auto snapshot = tracker.input_state()->drain();
    CHECK(snapshot.provider_count == 1);
    CHECK(snapshot.pressed_keys == std::vector<uint16_t>{ KEY_W, KEY_A });
    REQUIRE(snapshot.events.size() == 2);
    CHECK(snapshot.events[0].timestamp_ns == 100);
    CHECK(snapshot.events[1].code == KEY_A);

    // A drain empties the event log but keeps held state.
    snapshot = tracker.input_state()->drain();
    CHECK(snapshot.events.empty());
    CHECK(snapshot.pressed_keys.size() == 2);
}

TEST_CASE("KeyboardProvider: a sub-frame tap keeps its press event", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    auto provider = tracker.create_provider("window");

    provider->key_down(KEY_K);
    provider->key_up(KEY_K);

    const auto snapshot = tracker.input_state()->drain();
    CHECK(snapshot.pressed_keys.empty());
    CHECK(event_codes(snapshot, true) == std::vector<uint16_t>{ KEY_K });
    CHECK(event_codes(snapshot, false) == std::vector<uint16_t>{ KEY_K });
}

TEST_CASE("KeyboardProvider: focus loss releases only that provider's keys", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    auto window = tracker.create_provider("window");
    auto browser = tracker.create_provider("browser");

    window->key_down(KEY_W);
    browser->key_down(KEY_W);
    browser->key_down(KEY_A);
    tracker.input_state()->drain();

    browser->release_all();
    const auto snapshot = tracker.input_state()->drain();

    // W is still held through the window provider; the browser's releases are reported.
    CHECK(snapshot.pressed_keys == std::vector<uint16_t>{ KEY_W });
    CHECK(event_codes(snapshot, false) == std::vector<uint16_t>{ KEY_W, KEY_A });
    CHECK(snapshot.provider_count == 2);
}

TEST_CASE("KeyboardProvider: closing releases keys and detaches", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    auto provider = tracker.create_provider("window");
    provider->key_down(KEY_W);
    tracker.input_state()->drain();

    provider->close();
    CHECK(provider->is_closed());
    CHECK_FALSE(provider->key_down(KEY_A));

    const auto snapshot = tracker.input_state()->drain();
    CHECK(snapshot.provider_count == 0);
    CHECK(snapshot.pressed_keys.empty());
    CHECK(event_codes(snapshot, false) == std::vector<uint16_t>{ KEY_W });
}

TEST_CASE("KeyboardProvider: destruction releases keys", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    {
        auto provider = tracker.create_provider("window");
        provider->key_down(KEY_W);
    }
    const auto snapshot = tracker.input_state()->drain();
    CHECK(snapshot.provider_count == 0);
    CHECK(snapshot.pressed_keys.empty());
}

TEST_CASE("KeyboardInputState: undrained event log is bounded", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    auto provider = tracker.create_provider("window");
    for (std::size_t i = 0; i < core::KeyboardInputState::MAX_PENDING_EVENTS; ++i)
    {
        provider->key_down(KEY_W);
        provider->key_up(KEY_W);
    }
    provider->key_down(KEY_A);

    const auto snapshot = tracker.input_state()->drain();
    CHECK(snapshot.events.size() == core::KeyboardInputState::MAX_PENDING_EVENTS);
    CHECK(snapshot.events.back().code == KEY_A);
    CHECK(snapshot.pressed_keys == std::vector<uint16_t>{ KEY_A });
}

TEST_CASE("KeyboardProvider: concurrent providers and drains", "[unit][keyboard]")
{
    core::KeyboardTracker tracker;
    // Total events stay under MAX_PENDING_EVENTS so none can be dropped between drains.
    constexpr int kThreads = 4;
    constexpr int kIterations = 400;
    static_assert(static_cast<std::size_t>(kThreads * kIterations * 2) < core::KeyboardInputState::MAX_PENDING_EVENTS);

    std::vector<std::thread> threads;
    for (int t = 0; t < kThreads; ++t)
    {
        threads.emplace_back(
            [&tracker, t]()
            {
                auto provider = tracker.create_provider("thread" + std::to_string(t));
                const auto code = static_cast<uint16_t>(KEY_W + t);
                for (int i = 0; i < kIterations; ++i)
                {
                    provider->key_down(code);
                    provider->key_up(code);
                }
            });
    }
    std::size_t releases = 0;
    for (int i = 0; i < 100; ++i)
    {
        releases += event_codes(tracker.input_state()->drain(), false).size();
    }
    for (auto& thread : threads)
    {
        thread.join();
    }
    releases += event_codes(tracker.input_state()->drain(), false).size();

    CHECK(releases == static_cast<std::size_t>(kThreads * kIterations));
    CHECK(tracker.input_state()->drain().pressed_keys.empty());
}

TEST_CASE("evdev_code_from_w3c maps standard keys", "[unit][keyboard]")
{
    CHECK(core::evdev_code_from_w3c("KeyW") == KEY_W);
    CHECK(core::evdev_code_from_w3c("ArrowUp") == uint16_t{ 103 });
    CHECK(core::evdev_code_from_w3c("Numpad8") == uint16_t{ 72 });
    CHECK_FALSE(core::evdev_code_from_w3c("NotAKey").has_value());
}
