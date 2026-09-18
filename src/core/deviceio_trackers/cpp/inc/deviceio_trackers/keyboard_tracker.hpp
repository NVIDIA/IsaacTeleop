// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/keyboard_tracker_base.hpp>
#include <schema/keyboard_generated.h>

#include <cstddef>
#include <string>

namespace core
{

/*!
 * @brief Facade for raw keyboard press state exposed as ``KeyboardOutputTrackedT``.
 *
 * Semantic contract: ``pressed_keys`` is the set of currently-held Linux evdev key
 * codes; no semantic mapping (axis, toggle, ...) is applied here. After each
 * ``ITrackerSession::update()`` that includes this tracker, ``get_data(session)``
 * reflects the implementation's tracked snapshot. **Absent** data (``data`` null)
 * means no sample has been unpacked yet or the collection/source is unavailable.
 *
 * Usage:
 * @code
 * auto tracker = std::make_shared<KeyboardTracker>("keyboard");
 * // ... register the tracker with a session, then each tick: ...
 * session->update();
 * const auto& data = tracker->get_data(*session);
 * @endcode
 */
class KeyboardTracker : public ITracker
{
public:
    //! Default maximum FlatBuffer size for KeyboardOutput messages.
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 2048;

    /*!
     * @brief Constructs a KeyboardTracker.
     * @param collection_id Logical stream identifier; must match the data source for the chosen backend
     *        (see live implementation documentation).
     * @param max_flatbuffer_size Upper bound for serialized ``KeyboardOutput`` / record payloads
     *        (default: 2048 bytes); must be sufficient for the schema and backend.
     */
    explicit KeyboardTracker(const std::string& collection_id, size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    /*!
     * @brief Keyboard snapshot from the session's implementation.
     *
     * ``tracked.data`` is null when there is no valid last-known sample (source never
     * provided data or implementation cleared state when the collection is gone).
     */
    const KeyboardOutputTrackedT& get_data(const ITrackerSession& session) const;

    const std::string& collection_id() const
    {
        return collection_id_;
    }

    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    static constexpr const char* TRACKER_NAME = "KeyboardTracker";

    std::string collection_id_;
    size_t max_flatbuffer_size_;
};

} // namespace core
