<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `logging_config` (Python half of the logging system)

**CRITICAL (non-optional):** Before editing this package, complete the mandatory
`AGENTS.md` preflight in [`../../../../AGENTS.md`](../../../../AGENTS.md) (read
every applicable `AGENTS.md` on your paths, not just this file). The
cross-tree rules for *using* loggers are in that file under "Logging"; this
file is about changing the machinery itself.

## Module scope runs on every `import isaacteleop`

`isaacteleop/__init__.py` imports this package eagerly and then calls
`install()`. Anything at module scope here therefore executes before any caller
can guard it, on every platform the tree is built for — including the
experimental Windows build, which runs `import isaacteleop` during pybind11
stub generation.

- **Guard every POSIX-only facility at the point of use**, not at the call
  site. `_POSIX` in `_core.py` and `_HAS_UNIX_SOCKETS` in `_forwarding.py`
  exist for this. `os.getuid`, `os.O_NOFOLLOW`, `socket.AF_UNIX` and
  `socketserver.UnixStreamServer` are all absent on Windows.
- **A `class` statement evaluates its bases at import.** CPython defines
  `UnixStreamServer` inside `if hasattr(socket, "AF_UNIX")`, so a subclass of
  it must sit inside an equivalent guard — skipping the *call* is not enough.
- An unguarded POSIX call here is a **build** failure, not a runtime one: stub
  generation imports the package and fails the Windows job outright.
- **Tests must assert both branches.** The suite in
  `tests/python/core/logging_config/` is not gated on platform anywhere, so
  ctest runs it in the Windows job too. Mark POSIX-only assertions and give the
  degraded path its own assertions rather than only skipping.

## Leader and forwarding children

`ISAACTELEOP_LOG_SOCKET` decides which half of `_setup.install()` a process
takes. The leader owns the real console and file handlers and publishes a
receiver; every process that inherits the variable gets a forwarding handler
**and nothing else** — no console handler, no file handler, no fallback.

- That design assumes **the publisher outlives the processes that inherit the
  variable.** Any process deliberately spawned to outlive its launcher must
  drop `ISAACTELEOP_LOG_SOCKET` from the child environment, or it will ship
  records to a receiver that stops answering the moment the launcher exits and
  has nothing of its own to fall back on. `cloudxr/background.py` does this;
  `cloudxr/service/_service.py`'s runtime worker deliberately does not, because
  it is tied to the service's lifetime.
- The C++ half reads the same variable, so dropping it covers both.

## Native fd capture

`_native_fd.py` redirects fds 1 and 2 into files, never pipes. A pipe blocks
writes past its 64 KiB capacity until a reader drains it, and a drain thread in
this process needs the GIL while the native call doing the writing holds it —
the two deadlock. A write to a file needs nothing else to run. Do not
"simplify" this back to a pipe.

## Related

- C++ half: [`../../../core/log_bridge/AGENTS.md`](../../../core/log_bridge/AGENTS.md)
- Public API surface is `__all__` in `__init__.py`; `install()` is deliberately
  excluded and must be called only by the package bootstrap.
