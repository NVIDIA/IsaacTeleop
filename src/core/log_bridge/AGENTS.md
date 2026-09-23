<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `log_bridge` (C++ half of the logging system)

**CRITICAL (non-optional):** Before editing this package, complete the mandatory
`AGENTS.md` preflight in [`../../../AGENTS.md`](../../../AGENTS.md) and read
[`../AGENTS.md`](../AGENTS.md). The cross-tree rules for *using* loggers are in
the repo root file under "Logging"; this file is about changing the machinery.

## Two libraries, deliberately disjoint

- `cpp/` builds `log_bridge::log_bridge_core` and includes **no** pybind11 or
  `Python.h`. Standalone plugin executables and Catch2 test binaries link this
  and nothing else, so they can never reach the Python bridge.
- `python/` builds the `_log_bridge` extension, whose only job is
  `install_python_sink()`. It **replaces** a logger's sinks rather than adding
  to them, so a bridged record is formatted once, by Python's handlers. That is
  safe precisely because the symbol does not exist outside this module. Keep it
  that way; do not move bridge code into `cpp/`.

`logger.hpp` is the only public header. `isaacteleop::Logger::get()` is memoized
on the name, so repeated calls are cheap and always yield the same instance.
`LoggerKind::ThirdParty` is for loggers wrapping vendor/SDK output. It lowers
the *logger's* threshold from debug to trace and nothing else: visibility is
the sinks' decision — console at `ISAACTELEOP_LOG_LEVEL` (info by default),
file always at trace — so a vendor line logged at info reaches the console just
like one of ours. Both call sites (`ManusTracker::OnLog`, `mj_guard`) map the
vendor's own severity onto `debug`/`info`/`warn`/`error`, so the kind changes
nothing they emit today. Map a vendor severity onto `->trace()` to keep it off
the console until `ISAACTELEOP_LOG_LEVEL=trace`; the file keeps it either way,
and that is what the kind buys — an Application logger's `->trace()` is dropped
by the logger before any sink sees it.

**`local_sinks()` must not throw.** It is the function-local static behind
`Logger::get()`, which every call site in this tree treats as infallible — and
a static whose initializer throws stays uninitialised, so the next logging call
re-runs it and throws again. The console sink is therefore built before
anything that can fail, directory creation takes the `std::error_code`
overload, and the file sink is wrapped: an unwritable log directory costs the
file and nothing else.

**A log file is vetted twice, and `after_open` alone is not enough.** Every
rotation reaches `file_helper::open(name, truncate=true)`, which truncates
through `fopen(name, "wb")` with no `O_NOFOLLOW` — so a symlink standing at the
base name has its target truncated *before* `after_open` can look at the
descriptor. `before_open` (`reserve_log_file`) is what vets the name;
`after_open` (`harden_log_file`) only re-applies 0600 and `FD_CLOEXEC`, which
that same reopen would otherwise leave at the umask. Keep both, and do not
assume a check on the opened file can undo what opening it already did.

Neither hook may log — `sink_it_` holds the sink's mutex across them, so
logging from there deadlocks. `before_open` must throw if it cannot remove an
unsafe entry or reserve the name; returning would let spdlog's `fopen()` follow
the entry anyway. Do **not** redirect a failed check to `/dev/null`: it is
one-way (`/dev/null` reports size 0, so the sink never rotates again), silent,
and triggered by an operator `chmod` as readily as by an attacker.

**Known gap, not an oversight to re-report:** the rotating file sink's
descriptor can land on fd 0/1/2 when the host left one closed.
`socket_sink.cpp`'s `move_above_std()` works because `::socket()` hands over a
descriptor it then owns; `file_helper::open()` offers no such moment — it calls
`before_open` once, then retries `fopen` and calls `after_open` only on the
iteration that succeeds. Closing this needs an RAII guard on the per-record
logging path, which would pin `/dev/null` onto the host's fd 0/1/2 while held.

## `install_python_sink()` reaches one shared object, not the process

`log_bridge_core` is a static library, and roughly twenty targets link it —
including every pybind11 extension: `_oxr`, `_deviceio_session`, `_viz`,
`_robot_twin`, `_log_bridge`. Each shared object therefore carries its own copy
of `logger.cpp`'s bridge pointer, its own `local_sinks()`, and its own spdlog
registry, since spdlog is static too, and Python loads extension modules
`RTLD_LOCAL`, so nothing unifies them. `install_python_sink()` called through
`_log_bridge` configures `_log_bridge`'s copy and no other.

Those loggers still reach Python, by a different route: their module's own
`local_sinks()` picks a `SocketForwardSink` whenever `ISAACTELEOP_LOG_SOCKET` is
set, and the leader's receiver — in this same process — re-emits the record into
the Python tree. Where that transport does not exist, on Windows, those modules
fall back to their own console and file sinks and never enter the Python tree.

That fallback is why **no two log-file names may be derivable from the same
inputs**. A rotating file tolerates exactly one writer, and on Windows — or on
POSIX whenever `ensure_receiver()` cannot bind — the Python half and every
extension module's `local_sinks()` all want one in the same process at the same
moment. `_file.py` owns `<timestamp>.isaacteleop.<pid>.log`; C++ takes `.cpp`
and, past the first writer, a `-1`/`-2` suffix (`unique_log_path()`). Keep them
disjoint, and keep any new suffix out of the shape `rotating_file_sink` gives
its own backups.

Closing the split for real means giving the extensions shared logging state — a
shared `log_bridge` library, or an explicit per-module install — and a test that
emits from a second compiled extension and asserts a Python handler received it.
Neither is in place.

## The env-var contract is shared with Python, not parallel to it

`sink_config.cpp` and `socket_sink.cpp` read `ISAACTELEOP_LOG_DIR`,
`ISAACTELEOP_LOG_LEVEL` and `ISAACTELEOP_LOG_SOCKET` with the same meaning the
Python half gives them, and `SocketForwardSink` speaks the same wire format as
`logging_config/_forwarding.py`. A standalone C++ process with no interpreter
therefore forwards exactly like a Python child does. If you change the frame
layout, the field names, or how a variable is interpreted, change both halves in
the same commit or they silently stop understanding each other.

## Never log between `fork()` and `execvp()`

`plugin_manager/cpp/plugin.cpp` launches every plugin through that window, where
only async-signal-safe calls are legal. `Logger::get()` allocates and touches
spdlog's global registry, and in a Python process the bridge sink acquires the
GIL; both are unsafe there. Do not route the child's failure reports through a
logger — **nor through `std::cerr`**, whose `ostream::sentry` flushes `cout`
first and so copies whatever the *host* had buffered there into wherever fd 1
now points. Those reports use `write(2, …)`, which is on POSIX's list.

The same window points the **child's** fd 1 and fd 2 at
`ISAACTELEOP_NATIVE_CAPTURE_FILE`, which is how a plugin's non-logger output
stays off the terminal without the parent touching its own descriptors. The
child's descriptors are ours to set; the host's are not. `getenv` is *not*
async-signal-safe, so the path is read into a `const char*` **before** `fork()`.
A reader looking for a failed plugin launch should be pointed at that file.

## Related

- Python half: [`../../python/isaacteleop/logging_config/AGENTS.md`](../../python/isaacteleop/logging_config/AGENTS.md)
- spdlog is fetched in `deps/third_party/CMakeLists.txt`; when
  `BUILD_PLUGIN_OAK_CAMERA` is on it is built against vcpkg's fmt so DepthAI
  and this tree share one fmt. The reason is written there.
