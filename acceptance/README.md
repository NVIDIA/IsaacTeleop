<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Device integration acceptance

Deciding whether a third-party motion-capture integration works. The question is settled
from one recording of a prescribed motion script, so that a vendor is told what their
device did rather than what we guessed about it.

One directory per recordable schema, named after its `.fbs`. So far only
[`full_body/`](full_body); `hand` is the known next one. Each splits the same two ways:

| | |
|---|---|
| [`full_body/capture/`](full_body/capture) | What produces the MCAP: the spoken motion script, one take per run, and the label sidecar the posture checks read. |
| [`full_body/checker/`](full_body/checker) | What reads it: 38 checks over an MCAP, one verdict, plus a panel for what the text cannot show. |

The split is also a dependency boundary. `capture/` drives a real device through Isaac
Teleop, so it needs the built project and is **Linux only**; `checker/` runs on `mcap`
and `flatbuffers` alone on Linux or macOS, so a submitter can reproduce our verdict
without building anything.

## The seven gates

| Gate | Tests | Who runs it |
|---|---|---|
| G0 | The plugin builds with the vendor SDK present, and skips cleanly when it is absent. | You, on a machine that has the SDK. Ours does not. |
| G1 | Schema and channel conformance. | Us, from your recording. |
| G2 | Skeleton geometry — up axis, units, handedness, bone lengths, proportions, left/right labelling, joint indexing. | Us. |
| G3 | Signal quality — rate, jitter, dropouts, plausible joint speed. | Us. |
| G4 | Posture semantics — was each step of the script performed, in order, and does each joint angle read what the pose implies. | Us. |
| G5 | Replay through retargeting. | Nobody yet; see [`full_body/checker/AGENTS.md`](full_body/checker/AGENTS.md) before estimating this one. |
| G6 | A reviewer watches the video of the same session. | Us, by hand. Not automated by design. |

## Where to start

G0 is yours and comes first: it is a checklist you work through before opening the pull
request, plus a block of evidence you paste into the description.

Everything from G1 on needs a recording.
[`full_body/capture/README.md`](full_body/capture/README.md) is the step-by-step for
recording one, and [`full_body/checker/README.md`](full_body/checker/README.md) covers
the rest — how to set the checker up, how to read the verdict, how to send a take, and
what `pass`, `fail`, `retake` and `insufficient_data` each mean.

A verdict of `fail` says the device or its plugin is at fault. `retake` says the capture
is unusable because of how it was performed and the device is not implicated. Keeping
those apart is the specific mistake this process exists to avoid.
