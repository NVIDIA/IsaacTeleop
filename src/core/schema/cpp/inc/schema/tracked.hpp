// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Helper for the wrapper tables in `fbs/` that front a payload behind a `data` field:
// the `Record` family that MCAP writes, and `MessageChannelMessagesTracked`.
//
// Wrappers used to front the tracker query API too, expressing "no data" with a null
// `data`. `Serialized<T>` says that with an empty handle, so those are gone and trackers
// hand out their payload table directly. The message-channel batch survives because its
// `data` is a *list*: a drained batch needs a table to hold the vector, and "no messages
// this frame" is an empty batch rather than an absent one.
//
// Including this header is the signal that a translation unit depends on that shape.

#pragma once

#include <schema/serialized.hpp>

namespace core
{

/*!
 * @brief The `data` field of a wrapper, or null when there is none.
 *
 * Collapses "is the handle non-empty" and "is its `data` set" into one test.
 *
 * @note FlatBuffers omits an empty vector rather than encoding a zero-length one, so a
 *       null return means an empty batch, not missing data. Callers treat the two the
 *       same; do not read it as an error.
 */
template <typename T>
auto payload(const Serialized<T>& wrapper)
{
    return wrapper ? wrapper->data() : nullptr;
}

/*!
 * @brief The `data` field as a handle sharing the wrapper's buffer, empty when there is none.
 *
 * What a consumer that republishes the payload wants: narrowing re-points into the bytes
 * already owned rather than allocating a second buffer, and an absent `data` lands on an
 * empty handle without a branch at the call site.
 */
template <typename T>
auto narrow_payload(const Serialized<T>& wrapper)
{
    return wrapper.narrow(payload(wrapper));
}

} // namespace core
