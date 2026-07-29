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
- **`IDeviceIOSource` leaves are only discovered when reachable from a declared `OutputCombiner` output.** `TeleopSession._discover_sources` calls `pipeline.get_leaf_nodes()`, which walks back from the combiner's outputs. An input *source* whose only purpose is a side effect (e.g. message-channel send) must therefore expose at least one output (a heartbeat boolean is the established pattern) **and** the user's combiner must include it; silent no-discovery is the recurring footgun. **Output `IDeviceIOSink` nodes are different:** they are registered via `TeleopSessionConfig(sinks=[...])` and the session runs and flushes them explicitly each frame, so a sink needs no heartbeat output and no `OutputCombiner` reachability.
- **Run `clang-format` on touched C++ before pushing** — CI rejects unformatted C++ and pre-commit does not catch it. See the formatting instructions in the repo root [`AGENTS.md`](../../AGENTS.md) ("Pre-commit — match CI before you stop") for the exact commands; the source of truth lives there, not here.
- **A new pure-Python subpackage needs no build-system registration.** Drop the `.py` files under `src/python/isaacteleop/<name>/` (with an `__init__.py`) and they are staged by the `CONFIGURE_DEPENDS` glob in ``src/python/CMakeLists.txt`` and discovered by `[tool.setuptools.packages.find]`; there is no packages list or `DEPENDS` entry to update. This applies to authored `.py` only — a target that *builds* a file into the staging tree (an extension `.so`, a generated stub, a vendored runtime) still needs an explicit `DEPENDS` on ``src/core/python/CMakeLists.txt::python_package``, or Windows ninja will race the wheel build against it.
- **CloudXR join-main (Orin):** after the native service is up, do not start additional Python threads (including a ``sigwait`` helper). That re-triggers ``_PyGILState_NoteThreadState: Couldn't create autoTSSkey mapping``. Keep ``nv_cxr_service_join`` on the main thread only; rely on the launcher process teardown for shutdown while join blocks.
