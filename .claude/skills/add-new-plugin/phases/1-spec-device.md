---
description: >
  Interview the user about their device and produce a device.spec.yaml ready
  for Phase 2 to implement. Assumes an engineer who knows their hardware and nothing
  about IsaacTeleop: use the repo's terms, but define each one as you use it.
  Triggers on "I want to add / integrate my device into IsaacTeleop."
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Spec a Device — Phase 1

**Input:** the user's device description + any docs/SDK they have.
**Output:** `src/plugins/<device>/device.spec.yaml` with `status: ready`.

**Input devices only.** `direction: input` always — the skill does not cover feedback/output
devices. If the user's device only produces an effect (vibration, force), say it is out of scope
rather than specifying it.

**Assume an engineer who knows their device and nothing about IsaacTeleop.** Use the repo's own
terms — they are precise and the user is technical — but define each one in a clause the first
time it appears in a question. Never send a bare term, and never assume a definition carries over
from an earlier session.

Still yours to derive, never theirs: file paths, symbol names, node actions, factory rows.

### Terms you may use, with the gloss to reuse

| Term | Say it like this |
|---|---|
| plugin | the small standalone program that reads your device and feeds its data in |
| schema | the fixed record format one reading is stored as — field names, types, order |
| push / inject | whether your data travels as its own named format, or is fed into the headset's own hand tracking |
| CloudXR | the runtime that streams headset data to this machine |

`tracker`, `source node`, `channel_id`, `factory row`, and `node` stay off this list — you derive
them, so they never need to reach the user.

**Rule: gather first, ask only about gaps.** Draft from what you have; interview only what is
missing or ambiguous. Never go question-by-question when a bulk dump covers it.

## The template is the spec

Open `../examples/device.spec.template.yaml` before anything else. It is not an illustration —
it is the artifact you fill in. It defines every field, carries the `MUST-MATCH` annotations
inline (values that fail silently when wrong), and lists each of the seven nodes with its
`files` and `symbols` as `<name>` / `<Name>` placeholders.

You fill it in. You do not invent structure, and you do not describe a node's files from memory.

```
Step 1  dump       → user pastes everything; you ingest and explore the repo
Step 2  draft      → fill the template from evidence
Step 3  gaps       → list every unfilled or ambiguous field
Step 4  interview  → answer each gap from the material; ask the user only what it can't settle
Step 5  node plan  → set each node's action, files, symbols
Step 6  review     → confirm with the user, set status: ready, hand off
```

---

# Part A — Procedure

## Step 1 — Dump

Open with:
> *"Tell me about your device in your own words, and paste anything you have — protocol doc,
> SDK snippet, datasheet, or an example packet with what it means."*

While ingesting, explore the repo (never execute vendor scripts):
`src/core/schema/fbs/`, `src/plugins/`, `src/core/deviceio_trackers/`.

## Step 2 — Draft

Copy `../examples/device.spec.template.yaml`. Fill every field the evidence supports. Mark
inferred values with `# inferred` so they get confirmed later. Leave unknowns as `null`.

## Step 3 — Gaps

A gap is any: required field still `null` · unresolved fork · golden fixture missing ·
inferred value needing confirmation.

**A field the pasted material answers is not a gap** — even if finding it meant reading an SDK
header, a packet dump, or example code. Dig before you list it.

## Step 4 — Interview

**Two sources answer these questions: the material the user pasted, and the user. Try the
material first.** A protocol doc, SDK header, datasheet, or example packet usually settles field
meanings, units, counts, rates, and transport without asking anyone. Every question below is a
*fallback* for what the material cannot answer.

When the material answers it: record the value, mark it `# inferred`, and note where it came
from. It gets confirmed in Step 6 along with everything else — one review, not a question each.

When you must ask: one gap at a time, always with a default, saying what changes if the user
picks differently. Use `AskUserQuestion` for the two forks in *Schema design* — though those
are often answerable from the SDK too (a per-joint quaternion in the API settles Fork 1 without
a word from the user).

`AskUserQuestion` option labels are read without the surrounding prose, so each label carries its
own gloss: `Reuse joint_state (named joints, one angle each)`, not `joint_state.fbs`.

### 4a — Triage: is it already delivered natively?

Exactly four things arrive over OpenXR with every node already built. Match against this list —
not against "is it XR hardware", which is a different and larger set:

| Native device | Read by | Existing spec |
|---|---|---|
| Head pose | `LiveHeadTrackerImpl` | `../examples/head.device.spec.yaml` |
| Hands (26-joint skeleton) | `LiveHandTrackerImpl` (`xrLocateHandJointsEXT`) | `../examples/hand.device.spec.yaml` |
| Controllers (pose + buttons + axes) | `LiveControllerTrackerImpl` | `../examples/controller.device.spec.yaml` |
| Full body (24 joints, PICO only) | `LiveFullBodyTrackerPicoImpl` (`XR_BD_body_tracking`) | `../examples/full_body.device.spec.yaml` |

On the list → **stop.** It already works; point at the spec and say nothing needs to be added.

**Not on the list is not native, even if it plugs into the headset.** A localization / SE3
tracker puck is headset-adjacent hardware, but IsaacTeleop reads it through the
`controller_se3_tracker` **plugin** on the push path — `LiveSe3TrackerImpl` is a `SchemaReader`,
not an OpenXR reader. Same for any other vendor peripheral, base station, or accessory. If it
isn't one of the four above, continue the interview; it is almost certainly push.

Supporting a *new* OpenXR extension — as `full_body` once needed — means writing a live tracker
impl and a factory row, not a plugin. That is outside this skill.

### 4b — Environment

This decides which verification stages are achievable. **Check before asking.**

```bash
[ -f ~/.cloudxr/run/runtime_started ] && [ -S ~/.cloudxr/run/ipc_cloudxr ] && echo RUNTIME_UP
```

Only if that leaves it ambiguous:

> *"Is the device plugged into this machine right now?"*

> *"Is a headset connected — or is this machine running without one?"* (CloudXR, the runtime
> that streams headset data here, can run headless, so "no headset" is not a blocker by itself.)

Device not connected → stages 3–4 (runtime, e2e) cannot run; say so in the spec. No runtime →
record it in `whole_pipeline.notes` so Phase 2 doesn't block on it.

### 4c — Plugin binary name

User-facing tooling, so ask — the name shows up in commands they will type.

> *"The **plugin** is the small standalone program that reads your device and feeds its data in.
> What should its binary be called? (default: `<device>_hand_plugin` for a glove/hand device,
> e.g. `manus_hand_plugin`; otherwise `<device>_plugin`.)"*

It becomes the CMake target name, the `plugin.yaml` `command:` (`./<name>`), and the
install path `install/plugins/<device>/<name>` — which is what the grader and the live demo
look for (`run_manus_live.sh` defaults to `manus_hand_plugin`). Store it in node0's plugin
target field; Phase 2 must match it exactly.

### 4d — Data semantics

> *"Walk me through one reading from your device — every field, its meaning, units, count."*

Write down every field, its meaning, its units, and how many there are. Then pick the schema —
see **Schema design** in Part B. Do this before recording `delivery`: the schema choice settles it.

### 4e — Delivery

**Push, unless the device streams a full human-hand skeleton.**

| Delivery | When | Code |
|---|---|---|
| `push` | **Default.** Any data the runtime doesn't already know about | Plugin + schema → tracker → source |
| `inject` | A full 26-joint hand skeleton you want treated as the headset's own hand | Plugin only; everything downstream reused |

`inject` exists because `HandInjector` was written for hands. It is the only injector in the
repo, so it applies to hands and nothing else. If inject is chosen, see **Inject** in Part B for
what the spec must record.

You normally derive this from the data, but if you must confirm it:

> *"Two ways your data can travel: **push** — it arrives as its own named format, which is the
> normal path; or **inject** — it is fed into the headset's own hand tracking, so everything
> downstream treats it as the headset's hands. Inject only works for a full hand skeleton."*

**Reuse ≠ inject.** A glove that clones the pedal path *reuses* downstream code but still
*pushes* data.

### 4f — Plugin boundary

See **Plugin boundary** in Part B. Two questions to ask:

> *"Does your device need any separate application, dashboard, or service running alongside it
> — or does it work with just the device plugged in?"*

> *"Where does your device's code live today — repo, SDK archive, or just the doc?"*

## Step 5 — Node plan

1. Pick the closest example for its **shape**, not its values:

   | Classification | Copy from | What it shows |
   |---|---|---|
   | push — joint angles / positions | `so101_leader.device.spec.yaml` | `joint_state.fbs`, plugin + reuse downstream |
   | push — new small format (pedal-shaped) | `generic_3axis_pedal.device.spec.yaml` | new `.fbs` + full push pipeline |
   | push — clone of an existing format | `syn2.device.spec.yaml` | reuse existing tracker/source, deliver by push |
   | push — camera / bulk stream | `oak.device.spec.yaml` | metadata schematized, video out-of-graph |
   | inject — full hand skeleton | `haptikos.device.spec.yaml` | node0 create (plugin + `HandInjector`), nodes 1–6 reuse |

2. Keep all 7 nodes. Reuse/skip nodes stay one-line pointers.
3. Set each node's `action` (create / reuse / configure / skip).
4. Derive each node's `files` and `symbols` from the **template's** entries, substituting this
   device's name. Never carry another device's paths through — the copied example's values are
   placeholders.
5. Fill `verify.checks` with the user's golden values. Record each as **value + tolerance + how
   long it stays observable** — e.g. *"brake reaches 1.0 at the top of each 2 s sweep, held ~10 ms,
   tolerance 1e-3"*, never a bare `brake == 1.0`. A golden written as an instant becomes a
   single-frame equality check in Phase 2, which fails against a working pipeline. Exact equality
   is only for discrete state: status bits, integer counts, `is None`.
6. Leave `delivery_report`, `whole_pipeline.finish`, and every `verify` pass/fail STATUS empty —
   those belong to Phase 2.

## Step 6 — Review and hand off

Present the plan and wait. Show:

- Device: name, direction, delivery
- Schema: which `.fbs` is reused, extended, or created
- Nodes: which are create vs reuse, and the key new files
- Dependencies: any daemon, SDK, or XR requirement
- Assumptions and open questions

Resolve corrections before proceeding. Once confirmed, flip `status: draft → ready`, write to
`src/plugins/<device.name>/device.spec.yaml`, and hand off:

> *"The spec is ready. Run Phase 2 (build) to implement it."*

---

# Part B — Decisions

## Schema design

The schemas are their own reference — 15 FlatBuffers files in `src/core/schema/fbs/`, each
documenting its fields, units, and conditional population. **Read the closest one before
deciding. Never describe a schema from memory.**

### Three moves, in order of preference

| # | Move | When | Cost |
|---|---|---|---|
| 1 | **Reuse exactly** | Device data *is* an existing shape, no loss of information | Zero — tracker and source reused too |
| 2 | **Compose / extend** | Device data is a superset: closest schema plus extra fields (e.g. `hand.fbs` + tactile sensors) | New `.fbs`, downstream mostly reused |
| 3 | **New** | Fits nothing. Clone the closest `.fbs` and change what must change | Full stack: schema → tracker → source |

Prefer 2 over 3. A superset is not a new device — it is an existing shape with more on it.

**Never force a fit that loses information.** If fields don't fit, extend or go new. Dropping
data to make a schema match is the one outcome none of the three moves allows.

**If the fit is unclear, ask — once:** *"Your device sends X, which looks like
`joint_state.fbs`, but also includes Y. Extend that schema to carry Y, or treat this as a new
format?"*

### Where the device's data lands

| Device data | Schema |
|---|---|
| Full 26-joint hand skeleton (position + orientation per joint) | `hand.fbs` |
| Per-joint angles or 1D positions, name-keyed | `joint_state.fbs` |
| 2–3 continuous axes (pedals, sliders, triggers) | `pedals.fbs` |
| Single 6-DoF pose | `se3_tracker.fbs` |
| 6-DoF pose + buttons + axes | `controller.fbs` |
| 24-joint body skeleton | `full_body.fbs` |
| Opaque bytes | `message_channel.fbs` |
| Video + per-frame metadata | `oak.fbs` — see *out-of-graph* below |
| Superset of one of the above | extend that `.fbs` |
| None of the above | new `.fbs`, cloned from the closest |

### Compose from sub-schemas — never reinvent a primitive

Schemas are built from shared pieces, not written flat. `Pose` (`pose.fbs`) is position +
orientation and appears inside almost everything; `controller.fbs` composes a `Pose` with
buttons and axes rather than redeclaring pose fields. A new schema that declares its own
x/y/z/w won't interoperate with anything downstream.

### The wrapper convention

Every device schema is four declarations, not one:

```
table <Name>Output          # the data itself
table <Name>OutputTracked   # { data }             — tracker API; data is null when inactive
table <Name>OutputRecord    # { data, timestamp }  — what MCAP stores
root_type <Name>OutputRecord
```

A new `.fbs` defining only `<Name>Output` compiles, then fails at the tracker and recording
layers. Copy all four from the file you cloned.

### Out-of-graph data

**The invariant:** a high-bandwidth payload (video, depth, audio) does not travel through the
retargeting graph. Only per-frame *metadata* is schematized — enough to correlate the payload by
timestamp — and the payload itself goes somewhere else.

**Where it goes is the user's decision, not a default.** Ask:

> *"Your camera produces two very different things: a heavy video stream, and light per-frame
> information (stream name, sequence number, timestamp). Only the light part travels through
> the teleop pipeline. Where should the video itself go — written to files on this machine,
> streamed somewhere over the network, published on an existing topic, or dropped entirely?"*

Record the answer in the spec; the plugin implements it. `oak` is one instance of this, not the
template for it: its `main.cpp` takes a file path per stream and an optional `--mcap-filename`,
so writing H.264 to local files was a configuration choice for that device. Do not assume the
same for the next camera.

### The two forks

**Fork 1 (make-or-break).** A glove reporting **joint angles** → `joint_state.fbs`, push. A
glove reporting **full joint poses** → `hand.fbs`, inject. This one fact flips schema, delivery,
and how much code gets written. The SDK usually settles it — a per-joint quaternion means poses,
a scalar per joint means angles. If it doesn't:

> *"A **schema** is the fixed record format we store one reading in — field names, types, order.
> Does your glove report one number per joint (a bend angle), or a full position and orientation
> for each joint? The first maps onto `joint_state` (named joints, one value each); the second
> onto `hand`, the same format the headset's own hand tracking uses."*

**Fork 2 (only if Fork 1 landed on `hand.fbs`).** Inject — reusing the entire hand stack — is
the default. A custom SchemaIO pipeline is justified only when the data must travel as its own
named format.

## Plugin boundary

The plugin is **one standalone process built from `src/plugins/<device>/`**, launched by the
Plugin Manager. That folder is the deliverable — everything needed to build and run it lives
inside.

**Runtime — one process if you can get it.** The target is: plug in the device, start the
plugin, data flows. Prefer OS-native mechanisms — udev rules, `/dev/input/`, hidraw — which let
the plugin own the device lifecycle with nothing else running. `src/plugins/manus/` shows the
preferred shape: an `install_udev_rules.sh` run once on the host, then no vendor process at all.
A one-time setup step is fine; a permanently running one is what we are avoiding.

**Some devices genuinely require a vendor app, and that is acceptable.** Closed SDKs that only
expose a local socket, licence-checking services, calibration UIs that own the radio link — if
there is no way to talk to the hardware without it, use it. What is not acceptable is discovering
that dependency at build time. When a second process is needed, record in the spec:

- what it is, where it comes from, and what version
- how it is started, and whether it must already be running before the plugin launches
- what the plugin does when it is absent — fail with a clear message, never hang or crash silently

Phase 2 writes that into the plugin README as an installation prerequisite. Ask before assuming
either way:

> *"Does your device work once it's plugged in, or does it need a companion application or
> service running alongside it?"*

**Vendor material is reference, not a dependency.** The user's SDK, API docs, and existing
device repo are *inputs you read*, never a path the build points at:

- **reuse first** — check whether IsaacTeleop already implements what the plugin needs (a core
  library, or another plugin's target). If it fits reasonably, link it and record the dependency.
  If making the shared code fit would mean contorting it or the plugin around a near-match,
  implement it in the plugin folder instead and say why.
- **reimplement** the protocol/decode logic from the doc — minimal and unit-testable
- **copy the vendor's files in verbatim** — often right for wire formats, CRC tables, or an SDK
  header; record the upstream path, commit, and licence in the spec
- **never** `add_subdirectory()` a path outside the repo, or require the user's clone to exist
  at build time

## Inject

Only for a full hand skeleton (Fork 1). Record two things in the spec so Phase 2 builds it right.

**`node0.connection`:**

> *"plugin has no XR device dependencies — wrist position is best-effort, identity pose
> acceptable when absolute location is unavailable."*

This stops Phase 2 adding a `ControllerTracker` dependency, which crashes when no controller is
present.

**`wait_for_system=true`** in `OpenXRSession`. Inject plugins call `xrCreateHandTrackerEXT`, which
requires an active headset form factor. Without it, a plugin that starts before the headset
connects gets `XR_ERROR_FORM_FACTOR_UNAVAILABLE (-35)` from `xrGetSystem` and exits. This is the
contract for every inject plugin; push plugins do not need it.

## Files

- `../examples/device.spec.template.yaml` — the spec you fill in; field definitions and per-node
  files/symbols
- `../examples/*.device.spec.yaml` — one filled example per device type
