<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — IsaacTeleop `src/core` (index)

**CRITICAL:** The mandatory multi-file `AGENTS.md` preflight in **[`../../AGENTS.md`](../../AGENTS.md)** applies here too. Before changing anything under `src/core/`, you must have read **this file**, **the repo root `AGENTS.md`**, and **every other `AGENTS.md` on the directory paths you will touch**. Do not skip any of them.

To see **all** `AGENTS.md` files in the IsaacTeleop repo, use the **`find` command (or `**/AGENTS.md` glob) documented in the repo root [`AGENTS.md`](../../AGENTS.md)**—do not rely on a hand-maintained list in this file.

If work under **`src/core/`** went wrong—**user** correction, **pre-commit/CI** failure, or **repeated** same-class mistakes—you **must** follow the repo root **[`AGENTS.md`](../../AGENTS.md)** **Mandatory learning loop**: distill a short rule and **update** the **nearest** relevant `AGENTS.md` (this file or a package file) or **source comments** in the same session (including **delta vs `main`** scope).

- Async retargeting pacing behavior belongs on the pacing config objects; keep the worker focused on scheduling mechanics and avoid adding concrete pacing-mode or subclass branches there.
- Prefer coarse-grained async boundaries around an existing synchronous step before splitting DeviceIO/source polling away from graph execution; split internals only when a measured correctness or performance need justifies the extra thread-safety surface.
- In pipelined `TeleopSession`, `last_context` follows the returned completed frame; reset/control-transition events travel with that frame and must not force exact-current-frame waits. Use sync mode for exact current-frame behavior.
- Keep async retargeting comments short and local to invariants; user-facing pacing tuning guidance belongs in docs rather than long code docstrings.
- When changing `TeleopSession` retargeting execution defaults, update config, docs, and default-behavior tests together so opt-in vs. default semantics stay aligned.
- Preserve existing `TeleopSession` lifecycle flag semantics unless changing the public/context-manager contract intentionally; use tests to lock down cleanup details before altering them.
- After Python test or session-manager edits, let `ruff format`/pre-commit own wrapping and rerun the hook when it modifies files.
