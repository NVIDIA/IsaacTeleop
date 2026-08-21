<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `deviceio_base`

**CRITICAL (non-optional):** Before editing this package, complete the mandatory **`AGENTS.md` preflight** in [`../../../AGENTS.md`](../../../AGENTS.md) (read every applicable `AGENTS.md` on your paths, not just this file).

## API

- **`ITrackerImpl::update`** takes **`int64_t monotonic_time_ns`** (system monotonic clock, same domain as `core::os_monotonic_now_ns()`).
- **Do not** use `XrTime`, `<openxr/openxr.h>`, or OpenXR link targets in this library. Keep the tracker abstraction runtime-agnostic.
- **Query accessors return `Serialized<XPayload>`, never a generated `-T` and never a wrapper table.** The object-API types are an implementation detail of whoever assembles the payload; they must not appear in any `ITrackerImpl` or `ITracker` signature. See `<schema/serialized.hpp>`.
- **Keep `Serialized<T>` schema-agnostic.** It owns a buffer and re-points within it; it knows nothing about any field, so reaching one is the caller's job: `record.narrow(record->data())`. Narrow from the same handle you read the field through — `narrow()` pairs whatever pointer it is given with *this* handle's owner, so narrowing one wrapper onto another's field compiles and yields a handle owning the wrong buffer.
- **An empty handle is the absent payload** — device inactive, no sample yet, replay gap. Consumers test one condition (`if (handle)`). Do **not** reintroduce a wrapper table to carry optionality: that was what the `Tracked` tables did before the handle became nullable, and it made every read a two-step null check. The exception is the message channel, whose payload is a **list**: a batch needs a table to hold the vector, and "nothing this frame" is an empty batch rather than an absent one.

## Generated `I<Name>TrackerImpl` headers

Only **hand-written** trackers keep their `<name>_tracker_base.hpp` in `cpp/inc/deviceio_base/`.
The impl interface for a tracker declared in
[`../deviceio_trackers/trackers.toml`](../deviceio_trackers/trackers.toml) is generated into
`${CMAKE_BINARY_DIR}/generated/trackers/deviceio_base/` and reaches consumers through the same
`<deviceio_base/...>` include path, so a missing header there usually means a stale build tree
rather than a missing file. Do not hand-add a base header for a manifest tracker.

## CMake

- **`deviceio_base`** is an **INTERFACE** library: list only what the headers actually need (e.g. `isaacteleop_schema`). Do **not** link `OpenXR::headers` or `oxr::oxr_utils` here.
- The generated-header directory is added by the packages that consume it (`deviceio_trackers`,
  `live_trackers`, `replay_trackers`), not by this INTERFACE target.

## Fallout for dependents

- Targets that need OpenXR/oxr for compilation must declare those dependencies themselves (they are **not** implied by `deviceio_base`). See e.g. [`../live_trackers/AGENTS.md`](../live_trackers/AGENTS.md). **`deviceio_trackers`** intentionally stays OpenXR-free—see [`../deviceio_trackers/AGENTS.md`](../deviceio_trackers/AGENTS.md).
