<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# `mujoco_xr`: plan for splitting this branch into reviewable PRs

**This file is scaffolding and must be deleted before the final PR lands.** It
exists so that work on the four PRs below can be handed to separate agents on
separate branches without each of them re-deriving the split.

## Why

`jiwenc/mujoco-xr-app` is **9,051 insertions / 0 deletions across 53 files**.
That is not reviewable in one sitting, and the reason is not that any one piece
is bloated — it is that four unrelated changes, with four different review
audiences, are stacked in one branch.

```
3afc52c  add a MuJoCo XR app and rig                    +4511
a31a90e  add Franka and SO-101 scenes with full teleop  +4222   <- 46% of the branch
4ff6439  ship as a standalone wheel                      +588 -203
bbbf1c1  Let apps choose the XR reference space          +306   <- touches src/viz
89af321  namespace under isaacteleop_examples            +158  -79
ca6145f  drop --mode                                     +197 -604
```

One fact should shape how this is reviewed and therefore how it is split:
**8,900 of the 9,051 lines are new files in a new directory.** A reviewer cannot
regress anything by approving those. The only lines that can break something
that exists today are the **~140 lines under `src/viz/`**, and right now they are
buried under an example. Getting them out from under it is the single highest
-value part of this plan.

## The four PRs

| # | title | ~lines | depends on | audience |
|---|---|---|---|---|
| 1 | viz: app-selectable XR reference space | 230 | — | viz owners |
| 2 | examples/mujoco_xr: MuJoCo scene in XR + SO-101 leader gripper | ~3,000 | 1 | graphics / XR |
| 3 | examples/mujoco_xr: SO-101 and Franka scenes (2 commits) | ~1,100 | 2 | robotics / assets |
| 4 | examples/mujoco_xr: clutch + IK teleop | ~2,900 | 3 | robotics / controls |

They are strictly ordered. Each is independently useful and independently
revertible. **They do not have to all land**; stopping after 2 or 3 leaves the
tree in a coherent state. `jiwenc/mujoco-xr-app` gets rewritten/rebased as each
one merges.

---

## PR 1 — viz: let apps choose the XR reference space

Extract commit `bbbf1c1`, **minus** its `examples/mujoco_xr/` hunks.

### Files

| file | + |
|---|---|
| `src/viz/session/cpp/inc/viz/session/xr_reference_space.hpp` (new) | 38 |
| `src/viz/xr/cpp/openxr_session.cpp` | 48 |
| `src/viz/session/cpp/viz_session.cpp` | 18 |
| `src/viz/session/cpp/inc/viz/session/viz_session.hpp` | 11 |
| `src/viz/python/core_bindings.cpp` | 8 |
| `src/python/isaacteleop/viz/__init__.py` | 2 |
| `src/viz/python/session_bindings.cpp` | 1 |
| `src/viz/session/cpp/CMakeLists.txt` | 1 |
| `README.md` (root — client settings docs) | 11 |

### Why it is separate

It is an **API addition to viz that affects every viz consumer**, not just this
example. It carries the branch's only regression risk, it needs viz owners as
reviewers, and it has standalone value: `kLocal` (the old hardcoded behaviour)
puts the session origin at the headset's start pose, which is wrong for any app
drawing world-locked geometry at a height above the floor.

### Acceptance

- Existing viz tests stay green; the default stays `kLocal` so no current
  consumer changes behaviour.
- A runtime that cannot supply the requested space throws **naming the space**.
- `viz.XrReferenceSpace` is importable from Python.

### Note for the implementer

`bbbf1c1` also edits `examples/mujoco_xr/app.py` (+104/-4),
`examples/mujoco_xr/tests/test_app_helpers.py` (+58) and
`examples/mujoco_xr/cpp/frames.hpp` (+6/-5). **Those belong to PR 2**, which sets
`config.xr_reference_space = kLocalFloor` and derives its floor datum from it.
Do not carry them here.

---

## PR 2 — examples/mujoco_xr: a MuJoCo scene in XR, with the SO-101 leader gripper

The MVP. This is the PR that has to *prove the thesis*, and the thesis is:

> One OpenXR session, shared between `VizSession` (rendering) and
> `TeleopSession` (input). A MuJoCo scene drawn with Vulkan into images viz owns,
> handed to `ProjectionLayer.submit()` by CUDA pointer with no copy through host
> memory.

Nothing else in this repository does that, and everything else in this branch is
a feature riding on top of it.

### Scene: tabletop + the SO-101 leader gripper ghost

The visible content is `assets/tabletop.xml` plus
`assets/leader/leader_gripper.xml` — the three-part SO-101 leader gripper as a
**mocap body locked to the operator's right controller grip pose**.

This choice does a lot of work for its size:

- It is a **real mesh assembly** (3 STLs), so it exercises `mesh_buffers.cpp`
  and the `mjGEOM_MESH` path, not just boxes.
- It is **vendored, not fetched** (1.3 MB, Apache-2.0, from
  `TheRobotStudio/SO-ARM100`), so PR 2 needs no `fetch-menagerie.sh`, no
  `robot_spec.py` catalogue and no network step.
- Locking it to the controller makes **frame-convention errors visible**: if
  `cpp/frames.hpp` is wrong, the gripper is not in the operator's hand. That is
  the single most valuable thing to be able to see on first run, and it is why
  this beats an empty tabletop as an MVP.
- It subsumes what was previously scoped as a separate "leader ghost" PR.

`assets/leader/leader_gripper.xml` is already a self-contained `<mujoco>`
fragment with its own `<asset>` block and a `mocap="true"` body, so it includes
cleanly into `tabletop.xml`. Its current comment says it must be included *after*
`so101.xml` for geom ordering — **rewrite that comment for the tabletop case**;
the ordering constraint is "last", not "after the robot".

### Files to carry

**C++ renderer — all of it, unchanged (~2,050 lines).** This is irreducible:
MuJoCo's own renderer is OpenGL and cannot hand Vulkan images to viz.

```
cpp/scene_renderer.cpp        783    cpp/frames.hpp            110
cpp/render_target.cpp         409    cpp/mesh_buffers.cpp       91
cpp/mujoco_xr_bindings.cpp    299    cpp/mesh_buffers.hpp       63
cpp/render_target.hpp         156    cpp/shaders/scene.vert     50
cpp/scene_renderer.hpp        153    cpp/shaders/scene.frag     48
cpp/compile_shader.cmake       49
```

**Python.** `app.py`, slimmed — take the current file and remove everything
`a31a90e` added:

- delete the `robot_spec` import and all catalogue plumbing; `DEFAULT_SCENE`
  becomes `Path(__file__).parent / "assets" / "tabletop.xml"`
- delete `--scene`; **keep `--scene-xml`** as the escape hatch
- delete the `teleop` import, `_build_control`, `_draw_target_marker`,
  `CONTROL_HAND`, and the `control.*` calls in `_loop`
- **add** a ~15-line ghost update: write the right controller's grip pose into
  the `leader_ghost` mocap body each frame, gated on `GRIP_IS_VALID` exactly as
  `_draw_controller_markers` is

Keep `__init__.py` (35) — it is the single-`libmujoco` guard and is genuinely
load-bearing — and `__main__.py` (11).

**Assets.** `assets/tabletop.xml` (54), `assets/leader/*` (LICENSE 201,
`leader_gripper.xml` ~156, 3 STL LFS pointers).

**Tests.** `test_frames.py` (105), `test_projection.py` (100),
`test_app_helpers.py` (~130 after PR-2 slimming), `conftest.py` (~30 —
the synthetic-arm fixture belongs to PR 4), plus the **tracking half** of
`test_ghost.py`: that `mjv_updateScene` emits in geom-id order with the ghost
last, that the three leader parts form one assembly with sub-mm gaps, and that
the ghost follows the controller. The clutch-scaling and A-reset cases in that
file belong to PR 4.

**Build + docs.** `CMakeLists.txt`, `cpp/CMakeLists.txt`, `pyproject.toml`,
`tests/pyproject.toml`, `tests/CMakeLists.txt`, `.gitignore`,
`docs/source/getting_started/build_from_source/index.rst`, root `CMakeLists.txt`,
`rigs/mujoco_xr.yaml`, and a **README cut to ~150 lines** (see below).

### Two size levers, to decide explicitly

**(a) The dual build path.** `CMakeLists.txt` is 275 lines of which 153 are
comments, and `cpp/CMakeLists.txt` is 190 of which 103 are comments — over half,
because the example is configured **two ways**: `add_subdirectory`'d from the
root build *and* as a top-level scikit-build-core project. The README already
concedes "the extension gets compiled twice, and that is a consequence of the
design rather than a bug."

Collapsing to wheel-only saves ~150 CMake lines and deletes a whole conceptual
axis from review. **It is not free**: the in-tree path is what `ctest` runs
against, and moving ctest to the installed wheel is blocked on `isaacteleop`
being resolvable (it is on no index). Make this an explicit call in the PR
description either way; do not let it be inherited silently.

**(b) The README.** Currently 613 lines, of which `## Build` alone is 221.
Cut to ~150: Status, a ~40-line Build, Run, Frames, Tests. Move the design
rationale — why a separate wheel, why `pip install -e` breaks, why the mujoco
version is pinned in two places, why the extension compiles twice — into the
**PR description** or a `DESIGN.md`. Reviewers read PR descriptions; they skim
613-line READMEs, and a README that long signals "this is complicated" before
anyone reads a line of code.

**Do not cut the code comments.** ~24% of `app.py` is comments and nearly all of
them encode a bug someone already paid for: the NaN-safe `_clamp_dt` spelling,
the load-bearing control-before-physics order, the ungated-`xrSyncActions`
warning, the `should_render` gate on the stall watchdog. Fix the *cause* of the
CMake comments (lever **a**), not the comments.

### Acceptance

- `ctest -L mujoco_xr` green (CPU-only; see "Known traps").
- On a headset: the scene is visible, world-locked, and the leader gripper sits
  in the operator's hand.
- No `robot_spec`, no `teleop`, no `ik_dls`, no fetch script, no menagerie.

---

## PR 3 — examples/mujoco_xr: SO-101 and Franka scenes

**Two commits, in this order.** No teleop: the arms load, step, and stand at
their `home` keyframe. That is a legitimate, reviewable increment — it proves
scene loading, the fetch path, geom-type coverage and the table-at-`z=0`
invariant, with none of the control surface.

### Commit 1 — the scene catalogue and the SO-101

SO-101 goes first because it is the arm the PR-2 leader gripper belongs to and
the arm the production retargeters in PR 4 target.

| file | + |
|---|---|
| `python/isaacteleop_examples/mujoco_xr/robot_spec.py` | 531 |
| `scripts/fetch-menagerie.sh` | 137 |
| `python/isaacteleop_examples/mujoco_xr/assets/so101/ar_scene.xml` | 85 |
| `tests/test_scenes.py` | 256 |
| `.gitignore` (menagerie payload) | 17 |
| `app.py` — restore `--scene`, `_resolve_scene`, the catalogue | ~40 |

`robot_spec.py` is 531 lines and **exists only because there is more than one
scene**. Its jaw/TCP/actuator resolution is consumed by PR 4, not by this PR —
if it can be split so that PR 3 carries only the scene catalogue and PR 4 carries
the robot-kinematics half, do that. It is worth ~250 lines off this PR.

### Commit 2 — the Franka

| file | + |
|---|---|
| `python/isaacteleop_examples/mujoco_xr/assets/franka/ar_scene.xml` | 39 |
| `tests/test_scenes.py` (franka cases) | small |

Small on purpose: a second robot is what proves the catalogue is a catalogue and
not a hardcoded special case.

### Trap, already paid for once

MuJoCo resolves an `<include>`d file's `meshdir` against **the included file's
own directory**, and drops it when the wrapper lives elsewhere. That is why
`assets/franka/ar_scene.xml` says `<include file="panda.xml"/>` with no path and
why the fetched payload and the tracked wrapper must share a directory. The
`.gitignore` rule for the payload must stay at the **repository root** — moving
it into `examples/mujoco_xr/.gitignore` makes scikit-build-core strip the robots
out of the wheel.

---

## PR 4 — examples/mujoco_xr: clutch + IK teleop

### Reuse the production retargeters. Do not port `teleop.py` as-is.

`examples/mujoco_xr/python/isaacteleop_examples/mujoco_xr/teleop.py` (478 lines)
implements a clutch and a jaw mapping from scratch. **Both already exist in the
shipped package**, are unit-tested there, and must be used instead:

| use this | instead of |
|---|---|
| `isaacteleop.retargeters.SO101.clutch_retargeter.SO101ClutchRetargeter` | `teleop.Teleop`'s clutch/latch/engage logic |
| `isaacteleop.retargeters.SO101.gripper_retargeter.SO101GripperRetargeter` | `teleop.Teleop`'s trigger→jaw mapping |

`SO101ClutchRetargeter` emits an absolute 7D `ee_pose` (position + `xyzw`
quaternion) with the same output contract as `Se3AbsRetargeter`.
`SO101GripperRetargeter` emits a jaw closedness in `[0, 1]`. Both are
`BaseRetargeter` nodes, so they go **into the pipeline graph** that `app.py`
already builds in `_build_pipeline()` — this is not a library call, it is a graph
edge.

**`ik_dls.py` (299) stays.** There is no end-effector IK in the package: the
retargeters produce a Cartesian `ee_pose`, and something still has to turn that
into `d.ctrl`. That is what `ik_dls.py` is for.

### Integration risks — read these before writing code

1. **Frame contract.** `SO101ClutchRetargeter` requires the controller stream
   **already in the robot base frame**, and rebasing is upstream's job
   (`ControllersSource.transformed`). This example independently defines
   XR→MuJoCo in `cpp/frames.hpp` as a compile-time constant. Those two must
   agree, and nothing will tell you if they do not: the retargeter's docstring
   warns that a wrong rebase rotation "shows up as an intuitive-but-wrong
   hand-to-EE mapping, not as an error". **Decide on one source of truth and
   write down which.** This is the biggest risk in the PR.
2. **Execution state.** Engagement is `execution_state == RUNNING` **and**
   `squeeze > threshold`. The app currently supplies no execution events, so it
   must start doing so, and must hold `STOPPED` until the arm is at `home` — the
   retargeter's contract is explicit that a squeeze must not latch a home the arm
   has not reached.
3. **Reset.** The A button currently calls `Teleop.reset`. It should become an
   `execution_events.reset` pulse. Note the retargeter re-seeds from the
   **configured** home, not from live arm state, and the docstring spells out the
   ordering hazard when a frame carries both `reset` and an engage.
4. **Measured EE.** `MEASURED_BASE_T_EE_INPUT` is optional. Wiring it from
   `mjData` gives a jump-free re-engage after the arm sags or is pushed; leaving
   it unwired rides the last-commanded fallback. Wiring it is preferred here
   because the sim arm genuinely does sag.
5. **Rate limiting.** `SO101ClutchRetargeter` has none — `teleop.py`'s rate
   limiter and `_slew` have no equivalent in the package. Keep them, on the app
   side, downstream of the retargeter.

### Files

Carry `ik_dls.py`, `tests/test_ik_dls.py`, the synthetic-arm fixture in
`conftest.py`, the robot-kinematics half of `robot_spec.py`, and the
clutch-divergence + A-reset cases from `test_ghost.py`.

`tests/test_teleop.py` is **897 lines — the largest file in the whole branch,
larger than `app.py`**. Most of it tests a clutch that this PR deletes. Do not
port it wholesale. Salvage the cases that test *this example's* integration —
jaw polarity against `robot_spec`, the pure-translation-stays-pure check on the
SO-101, NaN `dt` through the rate limiter — and let
`retargeting_engine_tests/python/test_so101_retargeters.py` cover the clutch
algebra it already covers.

### Acceptance

- No clutch or jaw algebra remains in `examples/mujoco_xr/`.
- The frame agreement from risk 1 is asserted by a test, not by a comment.
- `ctest -L mujoco_xr` green.

---

## Known traps (all paid for already in this session)

- **The ctest glob runs at configure time.** `tests/CMakeLists.txt` does
  `file(GLOB test_*.py)`. Adding or deleting a test file leaves the entry list
  stale until you re-run `cmake --preset py3.12 -DBUILD_VIZ=ON`; a deleted file
  fails with `file or directory not found` rather than disappearing.
- **The mujoco probe runs at configure time too**, so a fresh clone needs
  configure → `uv pip install --python <build venv> "mujoco==3.11.0"` →
  configure again. The first pass necessarily prints `-- mujoco_xr: skipped`.
- **DCO sign-off is mandatory** for AI-drafted commits (`git commit -s`); a
  `commit-msg` hook enforces it. See `AGENTS.md`, which is **not** auto-loaded —
  read it.
- **clang-format is CI-enforced but not in pre-commit.** Run
  `clang-format-14 --dry-run --Werror` on touched C++ yourself.
- **Match CI's hook set**: `SKIP=check-copyright-year pre-commit run --all-files`.
- **No `mujoco_xr` test has ever run in CI.** Nothing in `.github/workflows/`
  installs `mujoco`, so the example is never configured and its tests are never
  registered. Green locally means one developer ran it. Wiring examples into CI
  is [#880](https://github.com/NVIDIA/IsaacTeleop/issues/880).
- **The Vulkan→CUDA→`submit()` path is covered by nothing** since `ca6145f`
  removed the GPU-backed `kOffscreen` test. Deliberate — it skipped everywhere
  except a GPU workstation — but PR 2 reviewers should know the renderer they
  are reading is unverified.

## Loose ends this plan does not cover

Two stale cross-references, both pointing at
`examples/retargeting/python/visualize_poses_mujoco_example.py`, which now lives
at `examples/cloudxr_mujoco_teleop/`:

- `examples/mujoco_xr/README.md` (~line 438, the Frames section)
- `examples/mujoco_xr/cpp/frames.hpp:38`

Fix them in PR 2, which touches both files anyway.
