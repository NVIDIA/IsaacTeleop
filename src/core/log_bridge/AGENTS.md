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

`PythonBridgeSink::sink_it_()` is exercised, but only through a test-only entry
point. `python_bindings.cpp` exports `_emit_test_warning()` when the build is
not a scikit-build wheel build, and
`tests/python/core/logging_config/test_logging_config.py`'s
`test_cpp_logger_reaches_python_through_real_bridge` calls it to put a real
record through the real bridge. Keep the symbol underscore-prefixed, out of
`isaacteleop/log_bridge/__init__.py`'s `__all__`, and behind
`ISAACTELEOP_LOG_BRIDGE_TESTING`: `pyproject.toml` deliberately passes no
`cmake.define` overrides, so `BUILD_TESTING` alone is ON in a `pip install`
build and would ship this symbol to users. `tests/cpp/core/log_bridge/
test_routing.cpp` covers the adjacent but different question -- the *seam*,
that `set_bridge_sink()` re-points every registered logger and the local sinks
drop out -- with a capturing stand-in, because what is under test there is
`logger.cpp`, not the bridge. The shared-logging-state work above is a
prerequisite for the cross-extension test, not for either of these.

## The env-var contract is shared with Python, not parallel to it

`sink_config.cpp` and `socket_sink.cpp` read `ISAACTELEOP_LOG_DIR`,
`ISAACTELEOP_LOG_LEVEL` and `ISAACTELEOP_LOG_SOCKET` with the same meaning the
Python half gives them, and `SocketForwardSink` speaks the same wire format as
`logging_config/_forwarding.py`. A standalone C++ process with no interpreter
at all therefore forwards exactly like a Python child does. If you change the
frame layout, the field names, or how a variable is interpreted, change both
halves in the same commit or they silently stop understanding each other.

One test holds the two halves together:
`tests/python/core/logging_config/test_logging_config.py`'s
`test_cpp_logger_reaches_the_python_receiver` stands up a real receiver and runs
`log_bridge_emit_record` -- the one-record executable in
`tests/cpp/core/log_bridge/emit_record/` -- against it, asserting every field the
frame carries. Nothing else compares a real C++ sender with a real Python
receiver, so do not let that test lapse into asserting against a hand-built
frame.

## Never log between `fork()` and `execvp()`

`plugin_manager/cpp/plugin.cpp` launches every plugin through that window,
where only async-signal-safe calls are legal. `Logger::get()` allocates and
touches spdlog's global registry, and in a Python process the bridge sink
acquires the GIL; both are unsafe there. The four `std::cerr` sites in that
window are correct as they stand — the rule is stated next to them in the
source, and this is the reminder not to "finish the migration" by moving them.

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
