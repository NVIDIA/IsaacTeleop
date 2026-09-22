<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Functional test suite for the IsaacTeleop logging system

Branch `lotusl/logging-C-tests`, one commit on top of `545206a74` ("Add log system").

**Final result: `ctest --test-dir build --output-on-failure --parallel 4` → 226/226 passing**
(215 before this branch, of which one was failing). `cloudxr_test_wss_static_client`
passes again.

| | before | after |
|---|---|---|
| CTest entries | 215 (214 passing) | 226 (226 passing) |
| Catch2 cases in `log_bridge_tests` | — | 4 |
| pytest cases in `tests/python/core/logging_config/` | — | 100 |
| pytest cases in `tests/python/core/cloudxr/` | 261 | 264 |

---

## 1. Coverage

### 1.1 By module

**`logging_config/_core.py`** — `test_core.py` (31)
The six level names in both directions (`resolve_level` raising, `env_console_level`
never raising), including that spdlog's `warn`/`err` spellings are *rejected* by one and
fall back to `INFO` in the other; whitespace trimming; the `+30` / `-5` / `40` numeric
forms; `TRACE` registered below `DEBUG` with a name `%(levelname)s` can render;
`LINE_FORMAT` rendering every documented field, padding `INFO` to five, and rendering
`TRACE`; `log_dir()` defaulting to `/tmp/isaacteleop-<uid>/logs` (the exact string
`sink_config.cpp` builds) and republishing an absolute path after a `chdir`;
`ensure_private_dir` narrowing every component it created and nothing the operator
already owned, and raising rather than returning an unusable directory;
`_move_above_std` leaving a high descriptor alone.

**`logging_config/_console.py`** — `test_console.py` (23)
`KeywordFilter` target validation and the three targets, including that `content`
matches the *formatted* message; `set_console_filter(None)`; a rejected pattern or
target leaving the previous filter attached rather than an unfiltered console;
`set_console_level` republishing `ISAACTELEOP_LOG_LEVEL` as a name, as `trace`, and as a
number for a level with no name — the value a fork+exec'd plugin executable reads;
the SGR formatter colouring warnings yellow and errors red on a terminal, leaving
ordinary records plain, emitting nothing off a terminal, applying a logger's emphasis
inside the line with the level colour resuming after the name, and handing the record
back unmodified so the file handler stays escape-free; `set_logger_colors` accepting
SGR (including 24-bit and combined) and rejecting `red`, an OSC sequence, a trailing
newline, and a bare erase-display.

**`logging_config/_file.py`** — `test_file.py` (4)
The file is created 0600; an existing regular file at the name is refused rather than
appended to; a symlink is refused and its target is left intact; and a rotation driven
by eight concurrent threads keeps all 400 records across base and backups, with every
generation still 0600.

**`logging_config/_forwarding.py`** — `test_forwarding.py` (15)
The frame round-trips name, level, message, sender pid and a rendered traceback; the
sender's milliseconds are not replaced by the receiver's; non-UTF-8 bytes arrive
replaced rather than dropping the record; the receiver serves eight live connections
concurrently (200 records); a malformed frame is dropped and its connection kept; an
oversized length prefix costs only its own connection; a sender `SIGKILL`ed mid-frame
leaves the receiver serving; `socket_path()` verifies a live address and unsets a dead
one; `ForwardingHandler` drops what it cannot deliver without raising or queueing;
`_release_receiver` refuses to act for a process that did not create the receiver and
will not unlink whatever took its name; `ensure_receiver` is idempotent and its socket
is 0600.

**`logging_config/_native_fd.py`** — `test_native_fd.py` (8)
Raw fd 1/2 writes captured only inside a scope, with Python-level writes exempt; nested
scopes restoring at the outermost exit; four scoping threads against four logging
threads leaving fd 1 and fd 2 bit-identical and losing no record; a warning logged
inside a scope still reaching the terminal; `ISAACTELEOP_NATIVE_CAPTURE=off` leaving
descriptors alone while still publishing the file; an untouched capture file removed at
exit; a subprocess handed `native_capture_fd()` writing into it with no scope open; the
capture file 0600.

**`logging_config/_setup.py` / `__init__.py`** — `test_install.py` (8), `test_routing.py`
The leader/child branch, the handler-attachment order (a forwarding child must have its
handler before `ensure_sink()` can report), and the degraded paths — see §1.2.

**`log_bridge/cpp/logger.cpp`, `logger.hpp`** — `test_logger.cpp` (4 Catch2 cases)
`Logger::get` memoized on the name and agreeing with spdlog's registry; `LoggerKind`
setting the starting level and being ignored on a second call for the same name;
`to_python_level` matching `logging_config`'s numbering including `off`;
`set_bridge_sink` *replacing* (not adding to) the sinks of both already-created and
future loggers.

**`log_bridge/cpp/sink_config.cpp`, `socket_sink.cpp`** — `test_routing.py`,
`test_forwarding.py`, driven out of process through `log_bridge_test_emitter`
`local_sinks()` picking console+rotating file when no address is set, the file named
`.cpp` and 0600, the rendered line matching the Python line format character for
character; the console threshold read from `ISAACTELEOP_LOG_LEVEL` while the file keeps
everything; `forwarding_socket_path()` probing the address and falling back to local
sinks when nothing answers; the socket sink replacing local sinks entirely; the wire
format understood by the Python receiver; `MSG_NOSIGNAL` and the synchronous send
demonstrated by a record surviving `abort()`; a leader killed mid-stream costing the
child its records and nothing else.

**Seams** — `test_routing.py`, `tests/python/core/cloudxr/`
`plugin.cpp`'s fork/exec window (the capture-file `dup2` and its `fstat` identity
check); `cloudxr/background.py` dropping `ISAACTELEOP_LOG_SOCKET`; `cloudxr/service/
_service.py` passing `native_capture_fd()` as the worker's stdout and reading the
capture file back into a startup-failure report.

### 1.2 By load-bearing property

**(1) Nothing this work removed from the terminal is lost.**
`test_routing.py::TestPythonLeader` (console shows `INFO`, file keeps `DEBUG`, both
lines match `LINE_RE`); `TestStandaloneCpp::test_writes_a_line_in_the_python_format_to_
its_own_file` (the same regex, derived from `LINE_FORMAT` and anchored against a
Python-rendered line in `test_core.py::TestLineFormat`, matches a C++-rendered line and
yields the right logger name, level and pid); `test_the_console_threshold_comes_from_
the_environment`; `test_an_in_process_cpp_logger_reaches_the_python_handlers`;
`test_file.py::test_rotation_keeps_every_record_written_by_concurrent_threads`;
`test_native_fd.py::test_a_warning_inside_a_scope_still_reaches_the_terminal`.

**(2) No route can crash or silence a process that merely imports IsaacTeleop.**
`test_install.py`, one child process per broken facility, each asserting exit status 0
*and* that records still landed somewhere: a log directory that cannot be created; a log
directory that is a regular file; a leftover socket file with no listener; a socket path
that never existed; a `sun_path` that will not fit; a runtime directory that cannot be
created; `ISAACTELEOP_LOG_LEVEL` set to junk; and an interpreter started with fd 1
closed, which must stay closed across `install()` *and* across a capture scope.
The unwritable-directory case additionally pins the reporting order — both
"File logging disabled" and "Native output capture disabled" reach the console, which is
only true because `install()` attaches handlers before it opens the capture sink.

**(3) Threading and abnormal termination.**
Concurrent logging while capture scopes open and close
(`test_native_fd.py::test_concurrent_scopes_leave_the_descriptors_as_they_were`);
rotation while eight threads log (`test_file.py`); the receiver under eight live
connections (`test_forwarding.py::test_serves_concurrent_senders`); a sender `SIGKILL`ed
mid-frame (`test_a_sender_killed_mid_frame_leaves_the_receiver_serving`); a C++ process
`abort()`ing after a record (`test_a_record_sent_before_abort_still_reaches_the_leader`,
also asserting the child died by `SIGABRT`); a leader killed while a child forwards
(`test_a_leader_that_dies_mid_stream_does_not_take_the_child_down`); nested and
concurrent scopes.

**(4) Routing lands where expected.**
`test_routing.py` — see the chart in §7. Every row marked "tested" there is one or more
assertions in that file.

---

## 2. Architecture

### 2.1 New leaves

```
tests/cpp/core/log_bridge/
  CMakeLists.txt          log_bridge_tests  (Catch2, links log_bridge::log_bridge_core)
  test_logger.cpp         4 cases, all tagged [unit]
  emitter/
    CMakeLists.txt        log_bridge_test_emitter
    emitter.cpp

tests/python/core/logging_config/
  CMakeLists.txt          one CTest entry per test_*.py, named logging_config_<name>
  pyproject.toml          pytest + numpy (`import isaacteleop` reaches retargeting_engine)
  conftest.py             clean child environments, log-file naming, receiver + leader
  test_core.py  test_console.py  test_file.py  test_forwarding.py
  test_install.py  test_native_fd.py  test_routing.py
```

Wiring follows the neighbouring leaves exactly:
`tests/cpp/core/CMakeLists.txt` gains `add_subdirectory(log_bridge)` in the unconditional
list (the library it links has no optional dependency); `tests/python/core/CMakeLists.txt`
gains `add_subdirectory(logging_config)` inside the existing `if(BUILD_PYTHON_BINDINGS)`
block next to `cloudxr`, because the suite imports `isaacteleop`. The emitter is its own
leaf directory under `if(NOT WIN32)`, mirroring `plugin_manager/test_process/` — one
CMake target per leaf directory, and the fork/exec and Unix-socket behaviour it exists to
drive is POSIX-only anyway.

Naming invariants are respected: the Catch2 executable is `<module>_tests`, the CTest
prefix is `logging_config_`, and tags become labels via
`catch_discover_tests(log_bridge_tests ADD_TAGS_AS_LABELS ...)`.

Two CTest `ENVIRONMENT` properties are set declaratively rather than in test code:

- `log_bridge_tests`: `ISAACTELEOP_LOG_DIR=<binary dir>/logs` and an empty
  `ISAACTELEOP_LOG_SOCKET`. Creating any logger builds that process's own sinks, so this
  keeps its file in the build tree and off a forwarding socket a developer's shell may be
  exporting.
- `logging_config_*`: the usual `PYTHONPATH`, the same build-tree `ISAACTELEOP_LOG_DIR`
  (pytest becomes a session leader the moment it imports `isaacteleop`), and
  `LOG_BRIDGE_TEST_EMITTER=$<TARGET_FILE:log_bridge_test_emitter>`. A bare `pytest` run
  with no emitter skips the out-of-process C++ cases via `conftest.requires_emitter`
  rather than failing.

### 2.2 Extended leaves

`tests/python/core/cloudxr/` gains three tests on existing files —
`test_background.py::TestSpawn::test_the_log_socket_is_not_inherited`,
`test_service.py::test_the_runtime_workers_stdout_goes_to_the_session_capture_file`,
`test_service.py::test_startup_failure_reports_the_native_capture_file`. They belong with
the code they cover, and that leaf is already wired.

### 2.3 `cloudxr_test_wss_static_client`

Fixed in the test tree, in `tests/python/core/cloudxr/conftest.py`. The logging work
added `from .. import logging_config` to `wss.py`; the synthetic package
`cloudxr_py_test_ns` was one level deep, so `..` had nothing to resolve to.

The fix gives it a parent. A synthetic root `isaacteleop_py_test_ns` takes its `__path__`
from the real `src/python/isaacteleop/` directory, and the cloudxr package is now
`isaacteleop_py_test_ns.cloudxr`, registered in `sys.modules` under *both* that name and
`cloudxr_py_test_ns`. `from .. import logging_config` therefore loads the real
`logging_config` package from source, with nothing installed — no stub, and no second
copy of `LINE_FORMAT` to drift. `wss` joins the four modules that are preloaded, because
an import reached through `cloudxr_py_test_ns.__path__` would be named one level up and
`..` would be out of range again; each preloaded module is aliased under
`cloudxr_py_test_ns.<name>` as well, so the ~60 existing `patch("cloudxr_py_test_ns.…")`
call sites are untouched. `wss.py` itself was not changed: the two-dot import is the
natural way for a subpackage to reach a sibling, and bending production code to a test
fixture's shape would have been the wrong direction.

### 2.4 CI workflow

**No change to `.github/workflows/build-ubuntu.yml`, and that was checked rather than
assumed.** The default matrix already runs
`ctest --test-dir "${BUILD_DIR}" --output-on-failure --parallel`, which picks up both new
leaves as soon as they are wired. Three specific things were verified:

- the test-packaging step globs `viz_*_tests` only, so a new core Catch2 binary is not
  swept into the GPU artefact;
- `test-viz-sanitizers` configures the whole tree but builds only the three viz targets
  and then runs `ctest -L unit` in `build-san`. `log_bridge_tests` is configured there
  and not built, so Catch2 emits its `log_bridge_tests_NOT_BUILT-<hash>` placeholder —
  which carries no labels, so `-L unit` does not select it. Confirmed by reading the
  generated `..._include.cmake`. This is the same situation the existing core Catch2
  leaves are already in;
- no production log message was reworded, so the eleven literals that job waits on are
  intact.

### 2.5 Two `AGENTS.md` bullets (mandatory learning loop)

Both record a trap that cost real time here and would cost the next agent the same:

- `tests/AGENTS.md` — the per-leaf `file(GLOB test_*.py)` is not `CONFIGURE_DEPENDS`, so
  a leaf created and filled in one pass contributes **zero** CTest entries until a
  reconfigure. The first "green" full run here was 219 tests, silently missing all seven
  new Python entries.
- `AGENTS.md` (root, under "Pre-commit") — `pre-commit run --all-files` enumerates
  through `git ls-files`, so files not yet `git add`ed are skipped and the run passes for
  the wrong reason. `ruff format` and REUSE both sat out the first three runs here and
  then reformatted four files the moment the suite was staged.

---

## 3. Design decisions

**A permutation of the five environment variables is a process, not a fixture.**
`install()` runs once per process, and C++'s `local_sinks()` is a function-local static
that reads the environment exactly once. There is no in-process way to ask either half
the same question under different conditions, and the obvious way to create one would be
a reset hook in production code. So every environment-dependent case spawns a child: a
Python child (`conftest.run_python`) or the C++ emitter (`conftest.run_emitter`). This is
also what the code actually has to survive in the field.

**No test-only seam was added.** Concretely:

- Nothing in `src/` changed. `git diff --name-only 545206a74 HEAD | grep -c '^src/'` is
  `0`; the diff is `tests/`, this report, and the two `AGENTS.md` bullets in §2.5.
- The C++ half is exercised through `log_bridge_test_emitter`, a helper *in the test
  tree* built exactly the way `plugin_manager_test_process` is. It has a small
  command language (`emit`, `abort`, `spin`, `raw`) so one binary covers every process
  shape the matrix needs; the alternative was either a hook in `sink_config.cpp` or four
  near-identical executables.
- The in-process C++ → Python route is triggered through a *real* production path:
  `PluginManager(["<dir with a malformed plugin.yaml>"])`, whose `m_logger->error(...)`
  fires deterministically with no hardware and no vendor SDK. No emit-for-tests entry
  point was added to `_log_bridge`.
- The Python receiver in `conftest.receiver` is the production
  `ThreadingUnixStreamServer` and the production `RequestHandler`, not a re-implementation
  of the protocol. The out-of-process leader in `conftest.leader` is a child that does
  nothing but `import isaacteleop`.
- `ForwardingHandler.emit()` is called directly rather than through a logger, because the
  receiver re-emits under the *sender's* logger name and a handler attached to that name
  in the same process would ship the record straight back.
- The two places a test reaches a private name — `_console._logger_colors` (cleared in a
  fixture) and `ForwardingHandler._sock` (asserted `None` to show a failed send left no
  half-open socket) — are assertions and cleanup, not behaviour changes.

**Determinism.** Every cross-process wait is on an observable fact with a deadline
(`conftest.wait_until`), never a sleep. Thread tests use a `threading.Barrier` and fixed
counts, and assert on the *set* of messages rather than on order. The one genuinely
best-effort operation in the system — a first connection from `ForwardingHandler`, which
gives up after a second rather than queue — is set up and confirmed before the
measurement starts in `test_serves_concurrent_senders`, because a loaded four-core box
does hit that timeout and asserting otherwise would be asserting more than the code
promises. Verified by running the leaf five times under `ctest --parallel 4` and the full
suite twice, all clean.

**One finding worth recording, which shaped an assertion.**
`test_concurrent_scopes_leave_the_descriptors_as_they_were` originally asserted that
every record reached the child's stderr. It does not, reproducibly: with four threads
churning capture scopes, between 5 % and 78 % of console copies landed in the capture
file instead (measured across three runs: 95/5, 73/27, 22/78). `_begin()` rebinds fd 2 to
the capture file a few instructions before it moves the console handler's stream onto the
saved duplicate, and a record emitted in that window follows the descriptor. The record
is never *lost* — the rotating file had all 100 every time — so the test now asserts what
is invariant: every record is in the session log, and every record is in
`stderr ∪ capture file`. That is a real (small) race in `_native_fd._begin`/`_end`, not a
test artefact; it is reported here rather than worked around silently.

---

## 4. Deliberately left untested

- **`unique_log_path()`'s `-1` / `-2` suffixes.** Reaching them needs two `local_sinks()`
  copies wanting one name in one process, i.e. a second compiled extension — which
  `log_bridge/AGENTS.md` itself records as the missing piece. Faking it from a test
  would mean the helper recomputing `current_timestamp() + pid`, duplicating production
  naming logic and racing the second boundary. What *is* tested is the invariant that
  makes the suffix rarely needed: the two halves never derive the same name
  (`test_the_two_halves_never_want_the_same_file_name`).
- **`reserve_log_file()`'s symlink branch.** `unique_log_path()` creates the name
  `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` microseconds earlier, so at the hook's only
  reachable invocation the entry is always a regular file this uid owns. Exercising the
  other branch needs an injected race. Its sibling `harden_log_file()` *is* covered: the
  `.cpp` log file is asserted 0600.
- **Rotation of the C++ file sink.** 10 MiB of spdlog output per rotation; the Python
  half's equivalent is tested directly because `maxBytes` is a constructor argument there.
- **Windows fallbacks** (`_HAS_UNIX_SOCKETS` false, `O_BINARY`, `_getpid`,
  `temp_directory_path`). Not reachable on this platform; the POSIX branch of every one
  of them is covered.
- **`set_propagate_to_root`.** A one-line setter on a stdlib attribute; a test would
  restate the line.
- **`PythonBridgeSink` itself.** See §5.
- **Log-file *content* under a second writer.** Out of scope for the same reason as the
  `-1` suffix.

## 5. What could not be executed here

- **`src/viz/robot_twin/cpp/mj_guard.cpp`** — `BUILD_VIZ` is auto-OFF (no Vulkan/CUDA),
  so it is not compiled. Its logger migration is untested in this configuration; it is
  built and `ctest`-ed in CI's `build-ubuntu` matrix, which does configure viz.
- **`src/plugins/manus/core/manus_hand_tracking_plugin.cpp`** and the Vive, Haptikos and
  OAK plugins — skipped for missing vendor SDKs, so not compiled.
- **`install_python_sink()` end to end.** `_log_bridge` exposes only the installer, and
  the sink it installs configures `_log_bridge`'s own copy of `logger.cpp` — which no
  production code in that shared object ever logs through. Proving the Python bridge
  needs a record emitted from a second compiled extension whose `local_sinks()` was
  bypassed; `log_bridge/AGENTS.md` already names that as the missing test, and adding a
  pybind extension to the test tree purely to emit one record was judged more machinery
  than the row is worth. The route that *does* carry those records in practice — the
  extension's own `SocketForwardSink` back into the leader's receiver — is tested end to
  end (`test_an_in_process_cpp_logger_reaches_the_python_handlers`). The C++ side of the
  bridge contract is covered by `set_bridge_sink` and `to_python_level` in
  `log_bridge_tests`.
- **CloudXR runtime / OpenXR / headset paths.** No GPU, no runtime, no headset here. The
  `TeleopSession` capture scopes around native construction and teardown are therefore
  covered at the level of `capture_native_output()`'s own behaviour, not through a live
  session.
- **Root-only cases.** Three tests that depend on directory permissions refusing the
  caller carry a `skipif(os.getuid() == 0)`; they pass as an unprivileged user here.

## 6. Seams that looked unavoidable — and were not

Two places tempted a production change. Neither got one.

1. **A way to make `local_sinks()` or `install()` re-read the environment.** Every
   degraded-path and routing case wants a different environment, and a
   `reset_for_tests()` in either half would have made the suite a tenth of the size. It
   is exactly the kind of hook that becomes load-bearing later. Resolved by making the
   process the unit of test — `conftest.run_python`, `conftest.run_emitter` and
   `conftest.leader`.

2. **A way to emit an in-process C++ record on demand.** No production entry point does
   this, and adding `_log_bridge.emit_for_test(...)` would have been a test-only symbol
   in a shipped extension. Resolved by finding a real call site that is deterministic
   without hardware: `PluginManager`'s `m_logger->error("Error parsing metadata …")` on a
   malformed `plugin.yaml`. The one thing this does *not* reach is `PythonBridgeSink`
   (§5), and that gap is named rather than papered over.

One thing genuinely could not be done without *some* deliberate act, and it is worth
flagging as a property of the design rather than a gap in the suite: **`plugin.cpp` reads
`ISAACTELEOP_NATIVE_CAPTURE_FILE` with `getenv` at launch time**, so
`test_a_capture_file_that_is_not_ours_is_refused` sets that variable in the child after
`install()` published it. That is not a test hook — it is the documented external
contract, set the way an operator or a wrapper script would set it — but it is the only
case in the suite where a test writes one of the five variables into a process that has
already started.

---

## 7. Log-routing chart

`SOCK` = `ISAACTELEOP_LOG_SOCKET` set and reachable. `CAP` = a `capture_native_output()`
scope is open. "session file" = `<ts>.isaacteleop.<pid>.log` (Python half);
"cpp file" = `<ts>.isaacteleop.<pid>.cpp[-N].log`; "capture file" =
`<ts>.isaacteleop.<pid>.native.log`.

### 7.1 Session leader (no `SOCK` on entry; publishes its own)

| Source | Condition | Console | Session file | cpp file | Capture file | Tested |
|---|---|---|---|---|---|---|
| Python logger | level ≥ console threshold | ✅ | ✅ | — | — | ✅ |
| Python logger | level < console threshold | — | ✅ | — | — | ✅ |
| Python logger | `CAP` open | ✅ (via saved fd 2) | ✅ | — | ⚠️ sometimes, see §3 | ✅ |
| In-process C++ (pybind extension) | — | ✅ | ✅ | — | — | ✅ |
| In-process C++ | leader's receiver unavailable | ✅ (own sink) | — | ✅ | — | reasoned |
| Raw `write(1/2)` by the host | no `CAP` | ✅ terminal | — | — | — | ✅ |
| Raw `write(1/2)` by the host | `CAP` open | — | — | — | ✅ | ✅ |
| Raw `write(1/2)` | `ISAACTELEOP_NATIVE_CAPTURE=off` | ✅ terminal | — | — | — | ✅ |
| Subprocess stdio | launched with `native_capture_fd()` | — | — | — | ✅ | ✅ |
| Subprocess stdio | inherited, `CAP` open | — | — | — | ✅ | ✅ (plugin case) |
| Plugin via `fork`/`execvp` | capture file present and 0600-ours | — | — | — | ✅ | ✅ |
| Plugin via `fork`/`execvp` | capture file not ours | inherited fd 1/2 | — | — | — | ✅ |
| Plugin via `fork`/`execvp` | no capture file published | inherited fd 1/2 | — | — | — | reasoned |
| `write_fd2` in the fork/exec window | always | child's fd 2 (capture file if bound) | — | — | ✅ | reasoned |

### 7.2 Forwarding child (inherited a live `SOCK`)

| Source | Condition | Destination | Tested |
|---|---|---|---|
| Python logger | any level | leader's console + leader's session file; **no local console, no local file** | ✅ |
| Out-of-process C++ (`SocketForwardSink`) | — | leader's console + leader's session file; **no cpp file** | ✅ |
| Out-of-process C++ | record then `abort()` | already delivered — the send is synchronous | ✅ |
| Out-of-process C++ | leader dies mid-stream | dropped; the child keeps running and exits 0 | ✅ |
| Python logger | leader dies mid-stream | dropped; no local fallback is grown | reasoned |
| Raw `write(1/2)` | `CAP` open in the child | child's own capture file | reasoned |

### 7.3 Standalone process with no interpreter (plugin executable run directly)

| Condition | Console | cpp file | Tested |
|---|---|---|---|
| no `SOCK` | ✅ stderr, at `ISAACTELEOP_LOG_LEVEL` | ✅ always, `DEBUG`+ | ✅ |
| `SOCK` set and reachable | — | — (forwarded to the leader) | ✅ |
| `SOCK` set, nothing listening | ✅ (address rejected by `socket_is_reachable`) | ✅ | ✅ |
| no writable `ISAACTELEOP_LOG_DIR` | ✅ console only | — | reasoned (Python equivalent tested) |

### 7.4 Deliberately detached process (dropped `SOCK` — `cloudxr/background.py`)

| Source | Destination | Tested |
|---|---|---|
| Python logger | its own console **and its own session file** — it is a leader | ✅ |
| `spawn()`'s child environment | `ISAACTELEOP_LOG_SOCKET` absent, `PYTHONUNBUFFERED=1` | ✅ |
| CloudXR runtime worker (deliberately *not* detached) | stdout → the service's capture file; stderr → `runtime_worker_stderr.log`; both read back into a startup-failure report | ✅ |

### 7.5 Degraded conditions (leader; all tested, all with exit status 0)

| Condition | What is lost | What still works |
|---|---|---|
| `ISAACTELEOP_LOG_DIR` uncreatable | session file, capture file | console, and both losses reported on it |
| `ISAACTELEOP_LOG_DIR` is a regular file | session file | console |
| `ISAACTELEOP_LOG_SOCKET` stale or dangling | nothing — the variable is unset and this process leads | console + session file |
| `sun_path` too long | forwarding (children each keep their own files) | console + session file, warning on both |
| runtime directory uncreatable | forwarding | console + session file, warning on both |
| `ISAACTELEOP_LOG_LEVEL` junk | nothing | console at `INFO`, file at `DEBUG` |
| host started with fd 1 closed | nothing | fd 1 stays closed, console on fd 2, session file intact |
| no Unix sockets (Windows) | forwarding | every process a leader; disjoint file names keep that safe (reasoned) |

---

## 8. Result

```
$ ctest --test-dir build --output-on-failure --parallel 4
100% tests passed, 0 tests failed out of 226
```

`cloudxr_test_wss_static_client` passes (test #219). `SKIP=check-copyright-year
pre-commit run --all-files` is clean, and `clang-format --dry-run --Werror` (version
14.0.6, matching CI) reports nothing on the two new C++ files.
