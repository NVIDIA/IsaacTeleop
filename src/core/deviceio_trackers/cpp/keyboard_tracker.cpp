// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/keyboard_tracker.hpp"

#include <chrono>
#include <unordered_map>
#include <utility>

namespace core
{

namespace
{

// Same clock as core::os_monotonic_now_ns() (CLOCK_MONOTONIC on Linux via libstdc++, QPC on
// Windows via MSVC); read through <chrono> because deviceio_trackers stays off oxr_utils.
int64_t monotonic_now_ns()
{
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

// W3C UI Events KeyboardEvent.code -> Linux evdev (linux/input-event-codes.h), standard
// 104/105-key layouts. Codes are physical key positions, so layouts do not affect them.
const std::unordered_map<std::string_view, uint16_t>& w3c_to_evdev()
{
    static const std::unordered_map<std::string_view, uint16_t> table = {
        { "Escape", 1 },
        { "Digit1", 2 },
        { "Digit2", 3 },
        { "Digit3", 4 },
        { "Digit4", 5 },
        { "Digit5", 6 },
        { "Digit6", 7 },
        { "Digit7", 8 },
        { "Digit8", 9 },
        { "Digit9", 10 },
        { "Digit0", 11 },
        { "Minus", 12 },
        { "Equal", 13 },
        { "Backspace", 14 },
        { "Tab", 15 },
        { "KeyQ", 16 },
        { "KeyW", 17 },
        { "KeyE", 18 },
        { "KeyR", 19 },
        { "KeyT", 20 },
        { "KeyY", 21 },
        { "KeyU", 22 },
        { "KeyI", 23 },
        { "KeyO", 24 },
        { "KeyP", 25 },
        { "BracketLeft", 26 },
        { "BracketRight", 27 },
        { "Enter", 28 },
        { "ControlLeft", 29 },
        { "KeyA", 30 },
        { "KeyS", 31 },
        { "KeyD", 32 },
        { "KeyF", 33 },
        { "KeyG", 34 },
        { "KeyH", 35 },
        { "KeyJ", 36 },
        { "KeyK", 37 },
        { "KeyL", 38 },
        { "Semicolon", 39 },
        { "Quote", 40 },
        { "Backquote", 41 },
        { "ShiftLeft", 42 },
        { "Backslash", 43 },
        { "KeyZ", 44 },
        { "KeyX", 45 },
        { "KeyC", 46 },
        { "KeyV", 47 },
        { "KeyB", 48 },
        { "KeyN", 49 },
        { "KeyM", 50 },
        { "Comma", 51 },
        { "Period", 52 },
        { "Slash", 53 },
        { "ShiftRight", 54 },
        { "NumpadMultiply", 55 },
        { "AltLeft", 56 },
        { "Space", 57 },
        { "CapsLock", 58 },
        { "F1", 59 },
        { "F2", 60 },
        { "F3", 61 },
        { "F4", 62 },
        { "F5", 63 },
        { "F6", 64 },
        { "F7", 65 },
        { "F8", 66 },
        { "F9", 67 },
        { "F10", 68 },
        { "NumLock", 69 },
        { "ScrollLock", 70 },
        { "Numpad7", 71 },
        { "Numpad8", 72 },
        { "Numpad9", 73 },
        { "NumpadSubtract", 74 },
        { "Numpad4", 75 },
        { "Numpad5", 76 },
        { "Numpad6", 77 },
        { "NumpadAdd", 78 },
        { "Numpad1", 79 },
        { "Numpad2", 80 },
        { "Numpad3", 81 },
        { "Numpad0", 82 },
        { "NumpadDecimal", 83 },
        { "IntlBackslash", 86 },
        { "F11", 87 },
        { "F12", 88 },
        { "NumpadEnter", 96 },
        { "ControlRight", 97 },
        { "NumpadDivide", 98 },
        { "PrintScreen", 99 },
        { "AltRight", 100 },
        { "Home", 102 },
        { "ArrowUp", 103 },
        { "PageUp", 104 },
        { "ArrowLeft", 105 },
        { "ArrowRight", 106 },
        { "End", 107 },
        { "ArrowDown", 108 },
        { "PageDown", 109 },
        { "Insert", 110 },
        { "Delete", 111 },
        { "NumpadEqual", 117 },
        { "Pause", 119 },
        { "MetaLeft", 125 },
        { "MetaRight", 126 },
        { "ContextMenu", 127 },
    };
    return table;
}

} // namespace

std::optional<uint16_t> evdev_code_from_w3c(std::string_view w3c_code)
{
    const auto& table = w3c_to_evdev();
    const auto it = table.find(w3c_code);
    if (it == table.end())
    {
        return std::nullopt;
    }
    return it->second;
}

// ============================================================================
// KeyboardInputState
// ============================================================================

uint64_t KeyboardInputState::add_provider()
{
    std::lock_guard<std::mutex> lock(mutex_);
    const uint64_t id = next_provider_id_++;
    held_by_provider_.emplace(id, std::set<uint16_t>{});
    return id;
}

void KeyboardInputState::remove_provider(uint64_t provider_id, int64_t timestamp_ns)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = held_by_provider_.find(provider_id);
    if (it == held_by_provider_.end())
    {
        return;
    }
    for (uint16_t code : it->second)
    {
        push_event_locked({ timestamp_ns, code, false });
    }
    held_by_provider_.erase(it);
}

bool KeyboardInputState::key_down(uint64_t provider_id, uint16_t code, int64_t timestamp_ns)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = held_by_provider_.find(provider_id);
    if (it == held_by_provider_.end() || !it->second.insert(code).second)
    {
        return false;
    }
    push_event_locked({ timestamp_ns, code, true });
    return true;
}

bool KeyboardInputState::key_up(uint64_t provider_id, uint16_t code, int64_t timestamp_ns)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = held_by_provider_.find(provider_id);
    if (it == held_by_provider_.end() || it->second.erase(code) == 0)
    {
        return false;
    }
    push_event_locked({ timestamp_ns, code, false });
    return true;
}

bool KeyboardInputState::tap(uint64_t provider_id, uint16_t code, int64_t timestamp_ns)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = held_by_provider_.find(provider_id);
    if (it == held_by_provider_.end() || it->second.count(code) != 0)
    {
        return false;
    }
    push_event_locked({ timestamp_ns, code, true });
    push_event_locked({ timestamp_ns, code, false });
    return true;
}

void KeyboardInputState::release_all(uint64_t provider_id, int64_t timestamp_ns)
{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = held_by_provider_.find(provider_id);
    if (it == held_by_provider_.end())
    {
        return;
    }
    for (uint16_t code : it->second)
    {
        push_event_locked({ timestamp_ns, code, false });
    }
    it->second.clear();
}

KeyboardInputState::Snapshot KeyboardInputState::drain()
{
    std::lock_guard<std::mutex> lock(mutex_);
    Snapshot snapshot;
    std::set<uint16_t> held;
    for (const auto& [id, keys] : held_by_provider_)
    {
        held.insert(keys.begin(), keys.end());
    }
    snapshot.pressed_keys.assign(held.begin(), held.end());
    snapshot.events = std::exchange(pending_, {});
    snapshot.provider_count = held_by_provider_.size();
    return snapshot;
}

void KeyboardInputState::push_event_locked(const Event& event)
{
    // Held state is authoritative; only the transition log is bounded, so dropping the
    // oldest events can never leave a key stuck.
    if (pending_.size() >= MAX_PENDING_EVENTS)
    {
        pending_.erase(pending_.begin());
    }
    pending_.push_back(event);
}

// ============================================================================
// KeyboardProvider
// ============================================================================

KeyboardProvider::KeyboardProvider(std::shared_ptr<KeyboardInputState> state, std::string name)
    : state_(std::move(state)), name_(std::move(name)), id_(state_->add_provider())
{
}

KeyboardProvider::~KeyboardProvider()
{
    close();
}

bool KeyboardProvider::key_down(uint16_t evdev_code, std::optional<int64_t> timestamp_ns)
{
    if (is_closed())
    {
        return false;
    }
    return state_->key_down(id_, evdev_code, timestamp_ns.value_or(monotonic_now_ns()));
}

bool KeyboardProvider::key_up(uint16_t evdev_code, std::optional<int64_t> timestamp_ns)
{
    if (is_closed())
    {
        return false;
    }
    return state_->key_up(id_, evdev_code, timestamp_ns.value_or(monotonic_now_ns()));
}

bool KeyboardProvider::key_down(std::string_view w3c_code, std::optional<int64_t> timestamp_ns)
{
    const auto code = evdev_code_from_w3c(w3c_code);
    return code.has_value() && key_down(*code, timestamp_ns);
}

bool KeyboardProvider::key_up(std::string_view w3c_code, std::optional<int64_t> timestamp_ns)
{
    const auto code = evdev_code_from_w3c(w3c_code);
    return code.has_value() && key_up(*code, timestamp_ns);
}

bool KeyboardProvider::tap(uint16_t evdev_code, std::optional<int64_t> timestamp_ns)
{
    if (is_closed())
    {
        return false;
    }
    return state_->tap(id_, evdev_code, timestamp_ns.value_or(monotonic_now_ns()));
}

bool KeyboardProvider::tap(std::string_view w3c_code, std::optional<int64_t> timestamp_ns)
{
    const auto code = evdev_code_from_w3c(w3c_code);
    return code.has_value() && tap(*code, timestamp_ns);
}

void KeyboardProvider::release_all(std::optional<int64_t> timestamp_ns)
{
    if (is_closed())
    {
        return;
    }
    state_->release_all(id_, timestamp_ns.value_or(monotonic_now_ns()));
}

void KeyboardProvider::close()
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_)
        {
            return;
        }
        closed_ = true;
    }
    state_->remove_provider(id_, monotonic_now_ns());
}

bool KeyboardProvider::is_closed() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return closed_;
}

// ============================================================================
// KeyboardTracker
// ============================================================================

KeyboardTracker::KeyboardTracker() : state_(std::make_shared<KeyboardInputState>())
{
}

std::shared_ptr<KeyboardProvider> KeyboardTracker::create_provider(std::string name)
{
    return std::make_shared<KeyboardProvider>(state_, std::move(name));
}

const Serialized<KeyboardOutput>& KeyboardTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IKeyboardTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
