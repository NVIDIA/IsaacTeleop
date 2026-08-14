<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `live_trackers`

**CRITICAL (non-optional):** Before editing this package, complete the mandatory **`AGENTS.md` preflight** in [`../../../AGENTS.md`](../../../AGENTS.md) (read every applicable `AGENTS.md` on your paths, not just this file).

## Time and OpenXR

- Store **`last_update_time_` as `int64_t`** (monotonic ns), not **`XrTime`**.
- **Once per `update` call:** `const XrTime xr_time = time_converter_.convert_monotonic_ns_to_xrtime(monotonic_time_ns);` then use **`xr_time`** for every **`xrLocate*`** / hand / body call **and** for MCAP (see below). **Do not** call **`convert_monotonic_ns_to_xrtime`** again in the MCAP block.
- **Full-body limp mode:** if the body tracker handle is null and you **return early**, **do not** compute **`xr_time`** first—only convert after you know you will call OpenXR.

## `DeviceDataTimestamp` (MCAP)

- **Fields 1–2:** monotonic ns (e.g. **`last_update_time_`, `last_update_time_`**).
- **Field 3 (`sample_time_raw_device_clock`):** the **same** **`xr_time`** variable used for OpenXR this frame (not a second conversion).

## Includes

- In headers that need both: **`#include <oxr_utils/oxr_funcs.hpp>`** comes **before** any bare **`#include <openxr/openxr.h>`**. `oxr_funcs.hpp` defines **`XR_NO_PROTOTYPES`** then includes OpenXR; including **`openxr.h`** first fights that policy.
- In **`.cpp`** files that construct **`DeviceDataTimestamp`**, include **`#include <schema/timestamp_generated.h>`** explicitly.
- **`.cpp`** files should include headers for **symbols the TU uses** (e.g. **`oxr_funcs.hpp`** for **`createReferenceSpace`**), not only what the matching **`.hpp`** happens to pull in.

## CMake

- **`live_trackers`** should **`PUBLIC` link `oxr::oxr_utils`** (OpenXR headers come through that INTERFACE target) because headers/sources use OpenXR / oxr types.

## Schema-based impls are generated

Live impls for trackers declared in
[`../deviceio_trackers/trackers.toml`](../deviceio_trackers/trackers.toml) are emitted into
`${CMAKE_BINARY_DIR}/generated/trackers/live_trackers/`; only hand-written trackers have `.cpp`
files in this directory. `live_deviceio_factory.{hpp,cpp}` stays hand-written but `#include`s
generated `.inc` fragments for the manifest trackers' forward decls, try-create thunks, dispatch
rows, and factory methods — **do not** add rows for a manifest tracker by hand.

Vendor routing is the reason the generated dispatch rows sit as one block at the end of
`k_tracker_dispatch`: manifest trackers are single-vendor, so their row order does not matter,
while multi-vendor hand-written types must keep their default vendor first.

## New tracker MCAP checklist

Applies to **hand-written** live tracker impls (`head`, `hand`, `controller`, `full_body`,
`message_channel`, …). For manifest trackers the impl, its MCAP
channels, and its recording traits are all generated — skip this checklist entirely.

When adding MCAP support to a new **hand-written** tracker impl, all of the following are required together—missing any one causes a build failure or wrong timestamps:

1. Add `XrTimeConverter time_converter_` and `int64_t last_update_time_ = 0` members to the impl header.
2. Initialize `time_converter_(handles)` in the constructor initializer list.
3. Declare `update(int64_t monotonic_time_ns) override` (not `XrTime`)—they are the same C++ type (`int64_t`) but semantically different; the base interface uses monotonic ns.
4. At the top of `update()`: store `last_update_time_ = monotonic_time_ns` and compute `const XrTime xr_time = time_converter_.convert_monotonic_ns_to_xrtime(monotonic_time_ns)`.
5. Use `DeviceDataTimestamp(last_update_time_, last_update_time_, xr_time)` — not `(time, time, time)`.
6. Add `MessageChannelRecordingTraits` (or equivalent) to `recording_traits.hpp` **above** its
   `generated_recording_traits.inc` include — that fragment is the manifest trackers' half.
7. **Always build** (`cmake --build <build_dir> -- -j$(nproc)`) before treating work as done. Pre-commit alone does not catch compile errors or clang-format violations enforced at build time.
8. Read `AGENTS.md` before starting. Not after CI breaks.

## Related docs

- Manifest and generator rules: [`../codegen/AGENTS.md`](../codegen/AGENTS.md)
- Session update loop: [`../deviceio_session/AGENTS.md`](../deviceio_session/AGENTS.md)
- No OpenXR in base API: [`../deviceio_base/AGENTS.md`](../deviceio_base/AGENTS.md)
- Replay counterpart: [`../replay_trackers/AGENTS.md`](../replay_trackers/AGENTS.md)
