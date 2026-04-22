<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `deviceio_session`

**CRITICAL (non-optional):** Before editing this package, complete the mandatory **`AGENTS.md` preflight** in [`../../../AGENTS.md`](../../../AGENTS.md) (read every applicable `AGENTS.md` on your paths, not just this file).

## Destruction order

- **`tracker_impls_`** lives in the **base** class; MCAP resources (`McapWriter`, `McapReader`) live in **derived** subclasses. C++ destroys derived members before base members, so every derived destructor **must** call **`tracker_impls_.clear()`** before its resource is destroyed—tracker impls may hold raw pointers into that resource.

## Update loop

- **`DeviceIOSession::update`** reads the clock once with **`core::os_monotonic_now_ns()`** (via `#include <oxr_utils/os_time.hpp>`) and passes that value to **`ITrackerImpl::update(int64_t)`** for every registered impl.
- **No** session-owned **`XrTimeConverter`** is required solely to drive that loop (OpenXR conversion stays inside live impls).

## Implementation / includes

- The public header **`deviceio_session.hpp`** includes **`oxr_session_handles.hpp`** (not `oxr_funcs.hpp`). It does **not** define `XR_NO_PROTOTYPES` or pull in vendor extension headers.
- **`deviceio_session.cpp`** includes **`<openxr/openxr.h>`** for **`XR_NULL_HANDLE`**; `XR_NO_PROTOTYPES` is not needed because the `.cpp` does not call OpenXR functions directly.

## Related docs

- Tracker interface contract: [`../deviceio_base/AGENTS.md`](../deviceio_base/AGENTS.md)
- Live factory + impls: [`../live_trackers/AGENTS.md`](../live_trackers/AGENTS.md)
