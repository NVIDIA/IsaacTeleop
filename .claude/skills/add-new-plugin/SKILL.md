---
name: add-new-plugin
description: >
  Add a new input device to IsaacTeleop — glove, pedal, tracker, camera, leader arm.
  Four phases: orient, spec, build, report. Produces a device.spec.yaml, a verified
  plugin under src/plugins/<device>/, and a report. Triggers on "add / integrate my
  device into IsaacTeleop". Input devices only.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Add a Device Plugin to IsaacTeleop

Takes a device IsaacTeleop has never seen — a glove, a pedal, a tracker, a camera, a leader arm —
and gets its data all the way to a robot command.

That means seven layers, in fixed order:

```
acquire → schema → tracker → bindings → source → boundary → robot step
```

A **plugin** reads the hardware and pushes its data in; a **schema** fixes the record format; a
**tracker** exposes it to C++; **bindings** expose that to Python; a **source** converts it to a
standard tensor shape; a **retargeter** turns that into joint commands. Most devices reuse most of
the chain — the work is deciding which layers already fit and building only the ones that do not.

The skill runs that as four phases: orient in the codebase, interview the user and write a spec,
build it node by node verifying each, then report what happened. The spec is the contract between
phases — Phase 1 decides and records, Phase 2 implements and proves.

## Phases

| Phase | Does | Read | Produces |
|---|---|---|---|
| 0 · Context | Orient in the codebase | `phases/0-teleop-context.md` | Key files read; the seven layers understood |
| 1 · Spec | Interview the user, pick the schema | `phases/1-spec-device.md` | `device.spec.yaml` with `status: ready` |
| 2 · Build | Implement node by node, verify each | `phases/2-build-device.md` | Verified plugin, tests, README |
| 3 · Report | Write up the run | `phases/3-onboard-report.md` | `report.md` |

**These are files, not skills — `Read` the path.** There is no `Skill()` to call for a phase.

Announce each phase as you enter it — *"Phase 2 (build): implementing the approved spec."* A
skipped phase should be visible in the transcript.

## Where to start

Start at the phase whose inputs you already have:

- Nothing but a user with a device → Phase 0, then 1.
- A `device.spec.yaml` with `status: ready` → Phase 2.
- A finished run, or its artifacts (`trajectory.jsonl`, `run.patch`) → Phase 3.

Each phase states what it requires. If you cannot satisfy it, go back one phase rather than
guessing.

**Invoked with no device in hand?** Print this table, say which phase you would start at, and
stop. Do not begin interviewing.

## Scope

**Input devices only** — devices that sense and feed data in. Feedback/output devices
(vibration, force) are not covered.

**Head, hands, controllers, and body are already native.** The runtime delivers them over OpenXR
and every node exists; there is nothing to add. Phase 1 triages this first. A device that merely
plugs into the headset is *not* native — see Phase 1, 4a.

## Shared files

- `examples/device.spec.template.yaml` — the spec every device fills in; defines every field and
  each node's files and symbols
- `examples/*.device.spec.yaml` — one filled example per device shape
- `troubleshoot.md` — CloudXR check / start / stop, and the traps

## Notes

- Phases 1 and 2 are sequential — Phase 2 needs an approved spec.
- Phase 0 can be read at any time; it is read-only orientation, no code changes.
- Phase 3 can run straight after Phase 2, or much later from collected artifacts.
- The user is an engineer who knows their device and nothing about IsaacTeleop. Use the repo's
  terms, but define each one as you use it — see Phase 1.
