---
description: >
  Implement a device.spec.yaml node by node, verifying each before moving on.
  Input: an approved device.spec.yaml (status: ready). Output: working, verified code +
  delivery report. A node is done when its check passes, not when it compiles.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Build a Device — Phase 2

**Input:** `device.spec.yaml` with `status: ready`.
**Output:** plugin code, tests, README, and `report.md` — all verified.

## The core rule

**A node is done when its check passes, not when it compiles.** Build one node, run its verify
command, fix until green, then move on. The same rule governs the e2e script: it is done when it
*runs* green, not when it is written.

```
Step 1  node loop     → for each of the 7 nodes: build → verify → fix → next
Step 2  runtime + e2e → probe for a runtime, start one, RUN the script
Step 3  finish        → whole-repo build, full ctest
Step 4  README        → install + testing, real commands only
Step 5  report        → hand off to Phase 3
```

---

# Part A — Procedure

## Step 1 — Node loop

`acquire → schema → tracker → bindings → source → boundary → robot step`

Each node in the spec carries `does / action / files / symbols / verify`.

- `action: reuse` — confirm it exists and is covered by tests; never edit it.
- `action: create` — write the code, write the test, run the check.

See `../examples/device.spec.template.yaml` — each node carries its own `files` and `symbols`.

| Node | What bites |
|---|---|
| **0** acquire | The plugin folder is the deliverable: vendor code is copied or reimplemented into it, never referenced from an external checkout. Prefer no second process, but if the spec records a vendor app as required, build against it and fail with a clear message when it is absent. For inject: see **Inject implementation** in Part B. |
| **1** schema | A new schema needs `.fbs` + pybind binding header + registration in `schema_module.cpp`. After adding a `.fbs`, cmake must **reconfigure**, not just rebuild, to regenerate the C++ headers. |
| **2** tracker | Add a row to **both** `live_deviceio_factory.cpp` and `replay_deviceio_factory.cpp`. A missing row links silently and fails at runtime: `unsupported tracker type`. Prove it by building the tracker **through the factory** in a test, not just as a standalone link. |
| **3** bindings | The import line is the test: `from isaacteleop.schema import <Name>Output` must pass. |
| **4** source | Must be reachable from an `OutputCombiner` output, or it is silently ignored. |
| **5** boundary | Usually **reuse** — an existing tensor shape in `standard_types.py`. Create one only when nothing matches. |
| **6** robot step | Usually **reuse** — existing retargeters already consume the standard shapes. |

## Step 2 — Runtime and e2e (`whole_pipeline`)

**Probe for a runtime. If one is available or can be started, running your e2e script is
mandatory** — see *Why e2e must actually run* in Part B.

```bash
# already up? readiness is BOTH markers — not cloudxr.env, which appears too early
[ -f ~/.cloudxr/run/runtime_started ] && [ -S ~/.cloudxr/run/ipc_cloudxr ] || {
  NV_DEVICE_PROFILE=Quest3 nohup python -u -m isaacteleop.cloudxr --accept-eula >/tmp/cxr.log 2>&1 &
  for _ in $(seq 1 120); do
    [ -f ~/.cloudxr/run/runtime_started ] && [ -S ~/.cloudxr/run/ipc_cloudxr ] && break
    sleep 0.5
  done
}
set -a; . ~/.cloudxr/run/cloudxr.env; set +a     # your script needs this env
```

Headless: `NV_DEVICE_PROFILE=Quest3` substitutes a device profile for a real headset, so no
headset is needed. It comes up in a couple of seconds.

On Isaac Teleop 1.5+ there is a service CLI that does this in one line
(`python -m isaacteleop.cloudxr.service status || ... start --accept-eula`). Try it; if it fails
with `No module named ...service` you are on an older build and the block above is correct.

**An empty `~/.cloudxr` does not mean CloudXR is missing** — the runtime ships in the wheel and is
copied there on first launch. See `../troubleshoot.md`.

Then run `python <the script named in whole_pipeline.verify.creates>` and fix until it passes.

### Writing the assertions

A device sim emits a **continuous** signal, so a spec golden is the value at an *instant*, not a
value that is there when you look. Poll a window and assert over it. Copy this shape:

```python
samples = poll(seconds=2.0)                       # a window, never a single frame
peak    = max(s.brake for s in samples)
assert peak >= GOLDEN_BRAKE - 1e-3                # peaks: >=, never ==
steady  = [s.aux for s in samples if abs(s.aux - GOLDEN_AUX) <= 1e-3]
assert len(steady) >= 5                           # N samples in band, not one lucky frame
assert 9 <= detents <= 11                         # counters: a range, not an exact count
```

Tolerances — do not invent tighter ones:

| Value | eps |
|---|---|
| float32 after a unit conversion | `1e-6` |
| crosses a network hop **and** a conversion | `1e-3` |
| counters / rates | assert a range, e.g. `9 <= n <= 11` |
| discrete state — status bits, integer counts, `is None` | exact equality is fine |

**Run it twice.** A test that passes once and fails once is flaky by definition, and the fault is
the assertion, not the pipeline. Two runs is the cheapest check in this phase.

### When e2e goes red

**Do not change plugin, tracker, or source code yet.** Work down this list first:

1. **Did stages 1–2 pass?** If yes, the wiring is sound — the fault is in stage 3 or in the
   assertion, not in the code you just wrote.
2. **Does the tracker return non-`None` data?** If yes, the channel is fine. This is a *value*
   problem, not a plumbing problem.
3. **Does the expected value appear in *any* frame of the window?** If yes — **the assertion is
   wrong, not the pipeline.** Widen it to a band and re-run.
4. Only if the value never appears across a full window is this a real decode or math bug.

A run that fails only a full-scale or exact-equality check while every other check is green is an
assertion bug until proven otherwise. Editing working code to satisfy a bad assertion is the
expensive failure here — it burns turns and can regress code that was already correct.

**If no runtime is available**, say so explicitly in `report.md`: the script is delivered but
unexecuted. Do not report the pipeline as verified.

Debugging aid: `python examples/deviceio_live_view/python/live_deviceio.py` shows hands, head,
controllers and full body live — use it to confirm data is flowing before running the script.

## Step 3 — Finish

```bash
cmake --build build          # whole repo, no target — not just your plugin
ctest --output-on-failure    # full suite, no -R; report the N/N count
```

Every test in the repo must pass. A red anywhere means not done.

Formatting is already gated by the `clang_format` ctest target, so the full suite covers it.
Git hooks and DCO sign-off are a contributor step, not part of this build — do not run them.

## Step 4 — Installation README

Write `src/plugins/<device>/README.md` covering two things only.

**Installation** — unboxed device to running plugin:
- Physical setup (cable, USB ID, pairing if wireless)
- Any driver, udev rule, or vendor application required — including whether it must already be
  running before the plugin starts
- Build flag to enable the plugin (e.g. `-DBUILD_PLUGINS=ON`)
- One command to confirm the OS sees the device (`lsusb`, `ls /dev/input/`, or equivalent)

**Testing** — one code block per script or test that exists:
- ctest entries for this device (`ctest -R <device_name>`)
- The plugin binary invocation with its arguments
- The e2e script, if one exists
- What a passing result looks like — one line of expected output

Rules: document only commands that actually exist, no placeholders. One read should take a new
developer from unboxed device to first data. Keep it short; link to
`IsaacTeleop/docs/source/device/add_device.rst` for background.

## Step 5 — Report

Produce `report.md` — see `3-onboard-report.md`.

---

# Part B — Rules

## The verification ladder

Five stages, each catching what the previous one cannot see:

| # | Stage | Proves |
|---|---|---|
| 1 | build | compiles, links, is registered |
| 2 | unit | the logic is right (schema, source, math) — no hardware |
| 3 | runtime | data actually flows |
| 4 | e2e | the values are right, end to end |
| 5 | finish | nothing else broke |

Stages 1–2 live inside each node's `verify`; stages 3–5 are Steps 2 and 3 above. What goes in a
node's verify block is shown per node in `../examples/device.spec.template.yaml`.

## Why bands, not frames

The rule in Step 2 exists because the numbers are brutal. Measured on a real pattern:

| assertion | how often it can be observed |
|---|---|
| `brake == 1.0` exactly | **5 samples in 1000** — one 10 ms sample every 2 s |
| `throttle >= 0.999` | 1 sample in 800 — a triangle peak, zero width |

Single-frame equality against those is a ~1-in-200 lottery: it fails against a *working* pipeline,
and the same test passes and fails on consecutive runs. This is the single most common cause of a
flaky e2e test — one that passes for its author and fails on replay.

## Silent failure map

| Failure | Symptom | Caught by |
|---|---|---|
| Plugin folder not registered | build target not found | stage 1 |
| `.cpp` missing from CMakeLists | undefined reference | stage 1 |
| Missing factory row | `unsupported tracker type` at runtime | stage 2 factory test |
| Broken Python binding | ImportError | stage 2 import line |
| Wrong `channel_id` | zero data, no error | stage 3 negative test |
| Wrong decode / math | wrong values | stage 2 goldens / stage 4 |

## Why e2e must actually run

Across 43 measured L3 runs, every agent that executed its own e2e script passed; every agent that
only wrote one failed. Same models, same spec.

The failures were not broken pipelines. They were plausible code written against interfaces that
do not exist:

- `DeviceIOSession([tracker])` → `TypeError: No constructor defined!`
  There is no constructor. Use the factory: `DeviceIOSession.run([tracker], handles)`.
- `build/Release/...` or `build/Debug/...` plugin paths → `FileNotFoundError`.
  Make and Ninja are single-config: there is no `Release/` subdir. After `cmake --install`, the
  binary is at `install/plugins/<device>/<device>_plugin`.

Both die on the first execution and are invisible to `ctest`. Running the script once is the
cheapest check in this skill.

## Inject implementation

Hands only — `HandInjector` is the sole injector in the repo. `HandInjector::push(joints, time)`
is the only call the plugin needs to make. Every rule below comes from a real failure:

- **No `ControllerTracker` dependency.** Reading the wrist root from a controller causes
  `xrSyncActions2NV` failures in headless/CloudXR sessions and crashes the worker loop when no
  controller is present.
- **No `wrist_valid` gate.** When the absolute wrist location is unknown, use an identity pose
  `XrPosef{{0,0,0,1},{0,0,0}}`. A hand at the origin is visible and useful; a deactivated
  injector is not.
- **No `std::exit` on XR errors** — log and continue. The skeleton callback fires independently
  of the XR session state.
- **Missing joints → zero-fill.** Do not skip injection because some joints are absent.
- **Inject every hand each cycle, not once per source callback.** Hand SDKs (e.g. Manus) deliver
  one side per callback, alternating left/right, so a given frame usually carries only one hand.
  If the plugin injects — or keeps active — only the side present in the current frame, the other
  side is deactivated and the hands **blink** (`L=Y R=-` ↔ `L=- R=Y`). Buffer the latest pose per
  hand and `push` **both** hands on every update cycle. (Equivalent: keep each injector alive and
  deactivate a side only after a short silence timeout, e.g. 0.5 s — never on a single absent
  frame.)
- **`wait_for_system=true`** in `OpenXRSession`, as the spec records. `xrCreateHandTrackerEXT`
  needs an active headset form factor; without it the plugin exits on
  `XR_ERROR_FORM_FACTOR_UNAVAILABLE (-35)` before the headset connects.

Reference: `src/plugins/controller_synthetic_hands/` — injection mechanics without a
controller-pose dependency.

## Code quality

- **No unnecessary abstractions** — add a class, helper, or layer only when it solves a real
  problem. Three similar lines beat a premature abstraction.
- **No defensive code for impossible cases** — trust the framework; validate at actual boundaries
  (user input, device SDK output).
- **No dead code, TODOs, or placeholder comments.**
- **No over-engineering** — implement exactly what the spec requires; do not design for
  hypothetical future devices.
- **Reuse over create** — use an existing schema, tracker, or source when the wire layout fits.

## Files

- `../examples/device.spec.template.yaml` — the spec being implemented; per-node files and symbols
- `../examples/*.device.spec.yaml` — one filled plan per device type
- `../troubleshoot.md` — CloudXR check / start / close, and the traps
