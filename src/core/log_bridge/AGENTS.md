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
  safe precisely because the symbol does not exist outside this module — the
  two populations are structurally disjoint, not switched by policy. Keep it
  that way; do not move bridge code into `cpp/`.

`logger.hpp` is the only public header. `isaacteleop::Logger::get()` returns a
bare `std::shared_ptr<spdlog::logger>` and is memoized on the name, so repeated
calls are cheap and always yield the same instance.

`LoggerKind::Application` defaults to debug; `LoggerKind::ThirdParty` defaults
to trace and is for loggers that wrap vendor/SDK output, so vendor chatter stays
silent unless someone explicitly lowers the threshold to TRACE.

**`local_sinks()` must not throw.** It is the function-local static behind
`Logger::get()`, which every call site in this tree treats as infallible — and
a static whose initializer throws stays uninitialised, so the next logging call
re-runs it and throws again. The console sink is therefore built before
anything that can fail, directory creation takes the `std::error_code`
overload, and the file sink is wrapped: an unwritable log directory costs the
file and nothing else.

**The directory is vetted the same way on both sides.** `ensure_private_dir()`
in the Python half and `directory_is_private()` here answer the same question:
the directory is ours by `lstat` (so a planted symlink is judged by its own
owner), and every lexical and resolved ancestor is owned by us or by root and
— where it is a real directory rather than a symlink — is not group/world
writable without the sticky bit. The default path is predictable
(`/tmp/isaacteleop-<uid>/logs`) and a standalone plugin executable never runs
the Python check, so a divergence here is a divergence in who can read the
logs. Failing the check costs the file sink; it must never throw.

## `install_python_sink()` reaches one shared object, not the process

`log_bridge_core` is a static library, and roughly twenty targets link it --
including every pybind11 extension: `_oxr`, `_deviceio_session`, `_viz`,
`_robot_twin`, `_log_bridge`. Each of those shared objects therefore carries
its **own** copy of `logger.cpp`'s `bridge_sink_storage()`, its own
`creation_mutex()`, its own `sink_config.cpp`'s `local_sinks()`, and its own
spdlog registry, since spdlog is static here too. Python loads extension
modules `RTLD_LOCAL`, so the dynamic linker never unifies them.

The consequence is easy to state wrongly, so state it precisely:
`install_python_sink()`, called through `_log_bridge`, mutates `_log_bridge`'s
copy of the bridge pointer and runs `spdlog::apply_all` over `_log_bridge`'s
registry. Loggers created inside `_oxr` or `_robot_twin` are in a different
registry and are unaffected.

Those loggers still reach Python, by a different route: their module's own
`local_sinks()` picks a `SocketForwardSink` whenever `ISAACTELEOP_LOG_SOCKET`
is set, and the leader's receiver -- in this same process -- re-emits the
record into the Python tree. That round trip is why the split is invisible on
Linux. Where the transport does not exist, on Windows, those modules fall back
to their own console and file sinks and their records never enter the Python
tree at all.

Do not write, or leave standing, a comment claiming that loading in-process
under a Python interpreter is sufficient for the bridge to apply. Closing the
split for real means giving the extensions shared logging state -- a shared
`log_bridge` library, or an explicit per-module install -- and an integration
test that emits from a second compiled extension and asserts a Python handler
received it. Neither is in place.

## The env-var contract is shared with Python, not parallel to it

`sink_config.cpp` and `socket_sink.cpp` read `ISAACTELEOP_LOG_DIR`,
`ISAACTELEOP_LOG_LEVEL` and `ISAACTELEOP_LOG_SOCKET` with the same meaning the
Python half gives them, and `SocketForwardSink` speaks the same wire format as
`logging_config/_forwarding.py`. A standalone C++ process with no interpreter
at all therefore forwards exactly like a Python child does. If you change the
frame layout, the field names, or how a variable is interpreted, change both
halves in the same commit or they silently stop understanding each other.

## Never log between `fork()` and `execvp()`

`plugin_manager/cpp/plugin.cpp` launches every plugin through that window,
where only async-signal-safe calls are legal. `Logger::get()` allocates and
touches spdlog's global registry, and in a Python process the bridge sink
acquires the GIL; both are unsafe there. Do not "finish the migration" by
routing the child's four failure reports through a logger.

**Nor through `std::cerr`, which is what they used to use.** The standard ties
`cerr` to `cout`, so `ostream::sentry` flushes `cout` before every write — and
the child inherited whatever the *host* had buffered there, which now lands in
whatever fd 1 points at. Since this same window rebinds fd 1 to the capture
file, one `std::cerr` in the child copied up to a buffer's worth of the host's
own stdout into isaacteleop's log. They use `write(2, …)` now, which has no
buffer of its own and is on the async-signal-safe list.

The same window now also points the **child's** fd 1 and fd 2 at
`ISAACTELEOP_NATIVE_CAPTURE_FILE`. `open`, `dup2` and `close` are on POSIX's
async-signal-safe list; `getenv` is not, so the path is read into a `const
char*` **before** `fork()` and only dereferenced afterwards. Keep it that way.

This is how a plugin's non-logger output — the OpenXR runtime's `xrCreate*`
diagnostics, the Manus SDK's own formatted lines — stays off the terminal now
that the Python half no longer rebinds the *host's* descriptors. The child's
descriptors are ours to set; the host's are not. Consequence to be aware of:
those four `std::cerr` sites now report into the capture file rather than the
terminal, which is where a reader looking for a failed plugin launch should be
directed.

## Related

- Python half: [`../../python/isaacteleop/logging_config/AGENTS.md`](../../python/isaacteleop/logging_config/AGENTS.md)
- spdlog is fetched in `deps/third_party/CMakeLists.txt`; when
  `BUILD_PLUGIN_OAK_CAMERA` is on it is built against vcpkg's fmt so DepthAI
  and this tree share one fmt. The reason is written there.
