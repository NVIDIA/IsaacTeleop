<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Full-body acceptance checker — plan and progress

Validates a third-party full-body motion-capture integration from an MCAP recording
alone. Design and gate definitions live in `design_agent-testing/`, which is local-only;
this directory is the implementation.

## Hard constraints

1. **No existing file is modified.** This directory is pure addition. `src/core` and every
   other tracked file stay untouched; `tests/no_core_changes` asserts it mechanically.
2. **`design_agent-testing/synthetic-fixtures/fixtures_index.json` and its `AGENTS.md` are
   read-only.** They are the oracle. Where this checker disagrees with the index, the
   disagreement is declared in `tests/known_deviations.py`, never by editing the index.
3. **New test data belongs here, not in the shared fixture set.** `generate_fixtures.py`
   rewrites the index as a side effect of adding a fixture, so cases this checker needs
   (Pico-shaped ones especially) are built by `tests/synth.py` into a temp directory.

## Layout

```
src/fullbody_acceptance/
  frames.py        Frame / JointPose / SourceMetadata, and the FrameSource protocol
  _schema.py       puts generated/ on sys.path; the only place that happens
  mcap_source.py   McapFrameSource — file order, never log-time order
  checks/base.py   Accumulator protocol, Status / Severity / Attribution, Outcome
  checks/*.py      one module per check group, named as the index names them
  report.py        Report model, verdict aggregation, JSON and text renderers
  cli.py           check-fullbody
tests/
  synth.py         builds MCAPs in-memory for unit tests and the Pico cases
  known_deviations.py
```

`setup_env.sh` builds `.venv`, fetches flatc **v24.3.25**, and generates the Python
bindings into `generated/`. It also re-checks that the `.bfbs` it produces is
byte-identical to `src/core/schema/golden/full_body.bfbs`, which is what ties this
checker to the schema the C++ writer actually embeds.

## Check names come from the index

The 22 defect fixtures each carry an `expected_failing_check`, so the check vocabulary is
already specified and is copied verbatim rather than invented:

| group | checks |
|---|---|
| `values` | `finite`, `zero_pose_on_valid_joint` |
| `quaternion` | `unit_norm_on_valid_joints`, `component_order` |
| `timestamps` | `monotonic`, `device_clock_distinct`, `available_not_before_sample` |
| `coverage` | `payload_presence_rate`, `validity_trend` |
| `rate` | `interval_regularity`, `frame_gaps` |
| `schema` | `required_field_present.joints` |
| `consistency` | `position_orientation_same_frame`, `all_joint_poses_tracked` |
| `continuity` | `max_joint_velocity` |
| `coordinate_frame` | `up_axis`, `handedness` |
| `units` | `position_scale_metres` |
| `skeleton` | `left_right_labelling`, `joint_index_assignment`, `bone_length_constancy`, `anthropometric_plausibility` |

## Interfaces

A check is an incremental accumulator (`update(frame)` / `result()`), so one
implementation serves an MCAP file, a live session and a replay session. `result()` can
return `INSUFFICIENT_DATA` from the first commit: that is the grey state in the live
panel and the correct answer offline for a recording too short to conclude anything.

Measurement and policy are separate. An accumulator reports `Status` plus its
measurements; the check *declares* `Severity` and `Attribution`, and verdict aggregation
is a pure function over the results. Thresholds can then be filled in later without
touching a measurement, which is what the graded G4 series exists to allow.

`Attribution` is present from the first commit even though every envelope check attributes
to the device. Collapsing `fail` (device's fault) and `retake` (human performance) is the
specific error the fixture set is built to catch, and retrofitting the distinction after
Slice 4 would mean reworking every check.

## Two checks are advisory, against what the index says

Both are cases where a hard failure would reject our own hardware.

**`consistency.all_joint_poses_tracked`** — `live_full_body_tracker_pico_impl.cpp` assigns
`all_joint_poses_tracked` straight from `locations.allJointPosesTracked` while `is_valid`
comes independently from each joint's `XR_SPACE_LOCATION_*_VALID_BIT`. The two can
legitimately disagree, so the disagreement is reportable, not a fault.

**`timestamps.device_clock_distinct`** — Pico writes
`DeviceDataTimestamp(last_update_time_, last_update_time_, xr_time)`, and on Linux
`xr_time` comes from `xrConvertTimespecTimeToTimeKHR`. A runtime that represents `XrTime`
as `CLOCK_MONOTONIC` nanoseconds makes the device clock equal the common clock on a
perfectly good recording. Unverified without hardware, and the locked design decision is
to treat unverified container details as informational.

`defect_all_tracked_flag_inconsistent` and `defect_device_clock_copies_common` therefore
report `pass` with an advisory where the index expects `fail`. Both are listed in
`tests/known_deviations.py` with this reasoning, and both should be revisited against the
first real recording.

## Test layers

The split is whether a test needs the fixture set, which lives outside git.

- **Unit** — accumulators fed frames built in memory by `tests/synth.py`. No MCAP, no
  external data, runnable from a fresh clone.
- **Oracle** — parametrised over `fixtures_index.json`, asserting `expected_verdict` and
  `expected_failing_check`. Needs `FULLBODY_FIXTURES` to point at
  `design_agent-testing/synthetic-fixtures`; skips when unset so a clone without the
  fixtures still runs green.

CI can only ever run the unit layer: the fixtures are not in git and the largest is
1.8 MB against pre-commit's 2000 KiB ceiling.

## Slices

1. `FrameSource` + `McapFrameSource`, the accumulator and report model, the CLI, and four
   checks: `values.finite`, `quaternion.unit_norm_on_valid_joints`, `timestamps.monotonic`,
   `coverage.payload_presence_rate`. Done when both goldens and all three benign fixtures
   pass, each of those four defects fails on its named check, and pytest is green.
2. The rest of the envelope and payload checks.
3. Geometry, behind a swappable skeleton profile — topology, symmetry pairs, proportion
   priors, speed ceiling, and which checks apply. `full_body` is the only profile;
   `hand` is the known next one. Gravity direction is body-only. Done: all nine geometry
   checks land, with the chirality findings below.
4. G4 measurement, validated against the graded series by accuracy and monotonicity
   rather than pass/fail.

Slice 5 (capture script, prompter, live panel, G5) needs hardware and is out of scope.

## Verified facts

- flatc v24.3.25 with the `GenerateFlatBuffers.cmake` flag set produces a `.bfbs`
  byte-identical to `src/core/schema/golden/full_body.bfbs`.
- `generate_fixtures.py` is deterministic: a full regeneration reproduced all 55 MCAPs,
  27 label sidecars and the index byte-for-byte (83/83 sha256 matches).
- `flatbuffers` 24.3.25 for Python has no reflection module, so payloads are decoded with
  flatc-generated bindings; the `.bfbs` is only ever byte-compared.
- `examples/CMakeLists.txt` registers subdirectories explicitly, but
  `src/python/CMakeLists.txt` globs `.py` recursively — adding a file there would change
  the wheel without editing anything, which is why this lives at the top level.

## What the chirality checks can and cannot separate

`coordinate_frame.handedness` and `skeleton.left_right_labelling` need a facing
direction, and the obvious source — the pelvis quaternion — is the wrong one: it makes
both checks fail on any recording whose orientations are wrong for an unrelated reason,
sending the submitter after the wrong defect. Both therefore derive forward from the mean
of the two ankle-to-foot vectors, which is position-only and, being a mean over the pair,
unchanged by either a mirror or a left/right swap. The feet are trusted only when both
are present, of plausible length against the torso, and pointing within 60° of each
other; a foot zeroed to the world origin otherwise passes a length test, because its
ankle is itself near the origin. Recordings without usable feet — back-filled endpoints,
and Pico, which does not report feet at all — fall back to the pelvis orientation, and
the outcome records which reference it used.

On a bilaterally symmetric skeleton, mirroring the rig and swapping the left/right labels
are the same transform, so `defect_mirrored_handedness` and `defect_left_right_swapped`
trip both checks identically and the collateral is declared in `known_deviations.py`.
Separating them needs an asymmetric subject, so it waits for a real recording.

`skeleton.joint_index_assignment` measures how much of a bone's length is spent moving
back toward the pelvis. Raw distance-to-root ordering does not work: an A-pose puts every
elbow nearer the pelvis than its shoulder, so a session spent in one is indistinguishable
from a permuted skeleton, which is what made the check fire on
`defect_validity_degradation`, where the surviving frames are all in the opening A-pose.
A reversed bone points straight at the root for a ratio of +1, while nothing correctly
indexed in the corpus exceeds −0.47, so the 0.8 threshold sits in an empty gap rather
than being tuned.

## Deferred

- Whether to vendor the generated bindings so the checker is distributable without flatc.
  Only matters for the live panel on a submitter's machine, i.e. Slice 5.
- Whether the fixture set ships with the checker as public test data.

## Progress

Appended as work lands; each entry is a commit on `ivany-nv/device-acceptance`.
