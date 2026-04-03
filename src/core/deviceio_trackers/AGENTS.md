<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `deviceio_trackers`

**CRITICAL (non-optional):** Before editing this package, complete the mandatory **`AGENTS.md` preflight** in [`../../../AGENTS.md`](../../../AGENTS.md) (read every applicable `AGENTS.md` on your paths, not just this file).

## No OpenXR dependency

- **`deviceio_trackers`** must **not** link **`OpenXR::headers`**, **`oxr::oxr_utils`**, or vendor extension targets, and must **not** `#include` OpenXR headers. Public API stays schema + **`deviceio_base`** only.

## Related docs

- Base interface: [`../deviceio_base/AGENTS.md`](../deviceio_base/AGENTS.md)
