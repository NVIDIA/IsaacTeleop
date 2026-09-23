// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/keyboard_tracker_base.hpp>
#include <schema/keyboard_generated.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

//! Evdev key code for a W3C `KeyboardEvent.code` ("KeyW", "ArrowUp", "Numpad8", ...), or
//! nullopt for a code with no standard-keyboard evdev equivalent.
std::optional<uint16_t> evdev_code_from_w3c(std::string_view w3c_code);

/*!
 * @brief Thread-safe key state shared by a KeyboardTracker, its providers and its impl.
 *
 * Providers report transitions from whatever thread their surface delivers events on;
 * the tracker impl drains once per frame on the session thread. Held keys are kept per
 * provider so one surface losing focus releases only its own keys.
 */
class KeyboardInputState
{
public:
    struct Event
    {
        int64_t timestamp_ns;
        uint16_t code;
        bool pressed;
    };

    struct Snapshot
    {
        std::vector<uint16_t> pressed_keys; //!< Union of every provider's held keys, sorted.
        std::vector<Event> events; //!< Transitions since the previous drain, in report order.
        std::size_t provider_count; //!< Providers open at drain time.
    };

    //! Bound on undrained events (no session running); the oldest are dropped past it.
    static constexpr std::size_t MAX_PENDING_EVENTS = 4096;

    uint64_t add_provider();
    //! Releases the provider's held keys, then forgets it.
    void remove_provider(uint64_t provider_id, int64_t timestamp_ns);

    //! Returns false when the transition changes nothing (autorepeat, or releasing an unheld key).
    bool key_down(uint64_t provider_id, uint16_t code, int64_t timestamp_ns);
    bool key_up(uint64_t provider_id, uint16_t code, int64_t timestamp_ns);
    //! Press and release in one step, for surfaces that report presses only. A no-op returning
    //! false when the provider already holds the key, so a tap never releases a real hold.
    bool tap(uint64_t provider_id, uint16_t code, int64_t timestamp_ns);
    void release_all(uint64_t provider_id, int64_t timestamp_ns);

    Snapshot drain();

private:
    void push_event_locked(const Event& event);

    mutable std::mutex mutex_;
    std::map<uint64_t, std::set<uint16_t>> held_by_provider_;
    std::vector<Event> pending_;
    uint64_t next_provider_id_ = 1;
};

/*!
 * @brief One input surface (a focused window, a browser tab, ...) feeding a KeyboardTracker.
 *
 * Contract for the surface: report press/release only while it has focus and its own UI is not
 * taking keyboard input, never report autorepeat as new presses, and call release_all() on blur,
 * close, disconnect, or when the host UI takes the keyboard, so no key can stay stuck. A surface
 * without release events reports tap(). Every method is thread-safe. Closing (or destroying) the
 * provider releases its keys.
 */
class KeyboardProvider
{
public:
    KeyboardProvider(std::shared_ptr<KeyboardInputState> state, std::string name);
    ~KeyboardProvider();

    KeyboardProvider(const KeyboardProvider&) = delete;
    KeyboardProvider& operator=(const KeyboardProvider&) = delete;
    KeyboardProvider(KeyboardProvider&&) = delete;
    KeyboardProvider& operator=(KeyboardProvider&&) = delete;

    //! Timestamps default to the monotonic clock at call time.
    //! Return false for a no-op transition or when the provider is closed.
    bool key_down(uint16_t evdev_code, std::optional<int64_t> timestamp_ns = std::nullopt);
    bool key_up(uint16_t evdev_code, std::optional<int64_t> timestamp_ns = std::nullopt);

    //! W3C `KeyboardEvent.code` variants. Unknown codes are ignored and return false.
    bool key_down(std::string_view w3c_code, std::optional<int64_t> timestamp_ns = std::nullopt);
    bool key_up(std::string_view w3c_code, std::optional<int64_t> timestamp_ns = std::nullopt);

    //! For surfaces that report presses only (no releases): records a press and its release
    //! together, so it reaches the per-frame pressed set without ever being held.
    bool tap(uint16_t evdev_code, std::optional<int64_t> timestamp_ns = std::nullopt);
    bool tap(std::string_view w3c_code, std::optional<int64_t> timestamp_ns = std::nullopt);

    //! Release everything this provider holds: on blur, close, disconnect, and whenever the host's
    //! own UI takes the keyboard (e.g. a text field gains focus).
    void release_all(std::optional<int64_t> timestamp_ns = std::nullopt);
    void close();

    bool is_closed() const;
    const std::string& name() const
    {
        return name_;
    }

private:
    std::shared_ptr<KeyboardInputState> state_;
    std::string name_;
    uint64_t id_;
    mutable std::mutex mutex_; // guards closed_ against a concurrent close()
    bool closed_ = false;
};

/*!
 * @brief In-process keyboard device: merges key events from every attached provider.
 *
 * Needs no OpenXR extension and no extra process. Surfaces attach through
 * create_provider(); the session publishes the merged state once per update and records
 * it to MCAP. In replay the recorded state is returned and provider input is ignored.
 */
class KeyboardTracker : public ITracker
{
public:
    KeyboardTracker();

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    std::shared_ptr<KeyboardProvider> create_provider(std::string name);

    //! Empty when no provider is attached (or, in replay, when the recording has no sample).
    const Serialized<KeyboardOutput>& get_data(const ITrackerSession& session) const;

    //! Shared state for tracker impls; not part of the user-facing API.
    const std::shared_ptr<KeyboardInputState>& input_state() const
    {
        return state_;
    }

private:
    static constexpr const char* TRACKER_NAME = "KeyboardTracker";

    std::shared_ptr<KeyboardInputState> state_;
};

} // namespace core
