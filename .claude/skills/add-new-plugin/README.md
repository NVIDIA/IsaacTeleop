<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# add-new-plugin

A Claude Code skill that integrates a new **input device** into IsaacTeleop — a glove, pedal,
tracker, camera, or leader arm — from "here is my hardware" to a verified plugin with a report.

You describe your device in your own words and answer a handful of questions. The agent reads
the codebase, decides which parts of the pipeline it can reuse, writes the code and the tests,
runs them, and tells you what it could and could not prove.

## Using it

```
> /add-new-plugin I want to add my XXX glove to IsaacTeleop, (the SDK is located at YYY)
```

Have your device's material ready to pass: protocol doc, path to SDK, product websites, datasheet, or an example packet with an explanation of its fields. The agent reads those first and only asks about what
they don't answer.

You will be asked to approve the plan before any code is written, and again if something
ambiguous comes up.

Scope: **Currently only support input devices.** Feedback devices (vibration, force) are not covered.

## What you get

| Output | Where |
|---|---|
| The agreed plan, as a spec | `src/plugins/<device>/device.spec.yaml` |
| Plugin, tests, and install/test instructions | `src/plugins/<device>/` |
| What was built and what was verified | `report.md` |


## Layout

```
SKILL.md                  entry point; the phase table
phases/0-teleop-context   orientation — what the system is, what to read
phases/1-spec-device      interview → device.spec.yaml
phases/2-build-device     implement node by node, verify each
phases/3-onboard-report   write report.md
examples/                 the spec template + one filled example per device shape
troubleshoot.md           CloudXR check / start / stop
```

Phases are markdown files the entry point reads, not separately registered skills — Claude Code
discovers only `.claude/skills/*/SKILL.md`, one level deep.
