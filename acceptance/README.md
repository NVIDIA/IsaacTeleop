<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Device integration acceptance

Deciding whether a third-party motion-capture integration works. The question is settled
from one recording of a prescribed motion script, so that a vendor is told what their
device did rather than what we guessed about it.

| | |
|---|---|
| [`fullbody/`](fullbody) | The checker for the `full_body` profile: 38 checks over an MCAP, one verdict, plus a panel for what the text cannot show. |
| [`capture/`](capture) | What produces that MCAP: the spoken motion script, one take per run, and the label sidecar the posture checks read. |

`full_body` is one profile and `hand` is the known next one, which is why the checker
sits a level down rather than at the top.

## The seven gates

| Gate | Tests | Who runs it |
|---|---|---|
| G0 | The plugin builds with the vendor SDK present, and skips cleanly when it is absent. | You, on a machine that has the SDK. Ours does not. |
| G1 | Schema and channel conformance. | Us, from your recording. |
| G2 | Skeleton geometry — up axis, units, handedness, bone lengths, proportions, left/right labelling, joint indexing. | Us. |
| G3 | Signal quality — rate, jitter, dropouts, plausible joint speed. | Us. |
| G4 | Posture semantics — was each step of the script performed, in order, and does each joint angle read what the pose implies. | Us. |
| G5 | Replay through retargeting. | Nobody yet; see [`fullbody/AGENTS.md`](fullbody/AGENTS.md) before estimating this one. |
| G6 | A reviewer watches the video of the same session. | Us, by hand. Not automated by design. |

## Where to start

G0 is yours and comes first: it is a checklist you work through before opening the pull
request, plus a block of evidence you paste into the description.

Everything from G1 on needs a recording. [`fullbody/README.md`](fullbody/README.md) has
the operator's guide — how to set the checker up, how to record a take, how to read the
verdict, and what `pass`, `fail`, `retake` and `insufficient_data` each mean.

A verdict of `fail` says the device or its plugin is at fault. `retake` says the capture
is unusable because of how it was performed and the device is not implicated. Keeping
those apart is the specific mistake this process exists to avoid.
