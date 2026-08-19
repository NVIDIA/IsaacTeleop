<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MuJoCo XR

A MuJoCo scene rendered stereoscopically into an Isaac Teleop Televiz XR
session: an SO-101 **follower arm** the operator drags around by hand, and an
SO-101 **leader gripper** that replaces it once the clutch engages.

Single process, single thread, **one** OpenXR session:

```
VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
     │                                        │
     │ recommended resolution                 │ EePoseRateLimiter output
     ▼                                        ▼
mjr_render ─blit─▶ flip + depth-invert ─glReadPixels─▶ PBO ═CUDA═▶ submit()
```

That is the thesis: `VizSession` (rendering) and `TeleopSession` (input) share
one OpenXR session via `get_oxr_handles()`, and **MuJoCo's own renderer**
reaches `ProjectionLayer.submit()` by CUDA pointer with no copy through host
memory. Nothing else in this repository does that.

**`cpp/` is a readback, not a renderer.** `mjr_render` draws into MuJoCo's
offscreen framebuffer; `cpp/gl_readback.cpp` blits that into a sampleable pair,
runs one fullscreen pass, and reads the result into a pixel-pack buffer that
CUDA imports. Every step stays in video memory. The GL half of `cpp/` — `gl.*`,
`gl_readback.*`, `gl_functions.inc` — is ~700 lines of it, and owns no shading,
no meshes and no camera maths beyond six frustum numbers.

The trick is which CUDA entry point is used. `cudaGraphicsGLRegisterImage`
registers no depth format and no multisampled renderbuffer, and
`mjrContext.offDepthStencil` is both — that is the wall a naive port hits.
`cudaGraphicsGLRegisterBuffer` has neither restriction, and `glReadPixels` into
a bound `GL_PIXEL_PACK_BUFFER` is a device-to-device transfer, so the CUDA-linear
buffer `submit()` already wants falls straight out of it.

The fullscreen pass exists for two conversions, both of which are silent
failures on anything short of a headset:

| | MuJoCo writes | ProjectionLayer is promised |
|---|---|---|
| row 0 | bottom (`glClipControl(GL_LOWER_LEFT, ...)`) | top |
| depth | reverse Z, near → 1 (`GL_GEQUAL`, `glClearDepth(0)`) | near → 0 |

The depth line is `1.0 - d`, which is exactly what MuJoCo's own
`mjr_readPixels` does on the CPU (`flipDepthIfRequired`, render_gl2.c); doing it
in the shader is what keeps the host out of the loop.

**What this costs.** One blit, one fullscreen pass and one pack-buffer copy per
eye per frame, all in VRAM, against a path that already copies image → staging
buffer → mailbox array → swapchain. **What it buys:** every geom type, the scene
XML's materials, lights, shadows and reflections, and MuJoCo's own mesh
handling.

`_mujoco_xr` links `libmujoco`, so this example ships as its own wheel rather
than inside `isaacteleop` — otherwise that wheel's contents would depend on
whether the build host happened to have `mujoco` installed. Exactly one
`libmujoco` may be loaded in the process, because `mjModel*` / `mjData*`
addresses cross the pybind boundary; `__init__.py` imports `mujoco` before the
extension and asserts both report the same version.

## Status — read this before anything else

| | |
|---|---|
| **Covered by tests** | [`ctest -L mujoco_xr`](#tests) — the frame conventions, the frustum, the clock, the ghost overlay and its jaw channel, the safety harness the ghost renders, the follower's head anchoring and rigid drag, and the whole clutch handoff driven at frame rate through the real pipeline, all pure CPU; **plus `test_readback.py`, which drives the real GPU path** (mjr_render → blit → flip/invert → PBO → CUDA). That one needs CUDA-OpenGL interop, so it wants a discrete NVIDIA GPU; it skips loudly elsewhere. **Measured on Jetson/Tegra it skips**, because `cudaGLGetDevices` reports the EGL context on no CUDA device — so a green `ctest` there does *not* mean the GPU path ran. |
| **Never executed anywhere** | **The XR half** — everything downstream of the readback. See [Not verified anywhere](#not-verified-anywhere-in-ci-or-on-a-developer-desktop). |
| **Wrong by construction until calibrated** | Nothing, now. The follower is placed against the **measured head pose** rather than the reference-space origin, and its offset is authored in the **XR** frame and pushed through `mj_from_xr`, so `kTransMjFromXr` appears once with each sign and cancels — see [Frames](#frames-cppframeshpp). |

Nothing in `.github/workflows/` installs `mujoco`, so the example is never
configured and **not one of its tests has ever run in CI**. Green means one
developer ran it locally. Wiring examples into CI is
[NVIDIA/IsaacTeleop#880](https://github.com/NVIDIA/IsaacTeleop/issues/880).

## Scope

Renderer + MuJoCo + rig, and one scene: `assets/scene.xml` — an **SO-101
follower arm** and an **SO-101 leader gripper ghost**, exactly one of which is
drawn at a time. No table, no blocks, no ground plane: this is an AR scene and
passthrough is the background.

The ghost is not decoration. It is a real mesh assembly (4 fetched STLs, so it
exercises the `mjGEOM_MESH` path), and locking it to the hand makes the *grip*
calibration visible — whether the tool sits in the hand the way a hand holds
one. It cannot show a wrong `cpp/frames.hpp`: those constants place it, and the
eye pose reaches MuJoCo world through the same ones, so they cancel and the
ghost lands in the hand whatever they say. Only static content shows them, and
the shipped scene has none.

**Its trigger is driven by the shipped `SO101GripperRetargeter`, as a graph
edge** — the retargeter is a `BaseRetargeter` node inside `_build_pipeline()`,
not a library call beside it, and its closedness output reaches `mjData` and
therefore the screen. There is no robot in the scene, so the jaw it drives is
the operator's own trigger; that is enough to show the edge is live, and the
SO-101 that will read the same output arrives with the scene catalogue.

**And its pose is the safety harness's output, not the controller's** — see
[The harness the ghost renders](#the-harness-the-ghost-renders). What that
harness governs is the **clutch's** output; see
[The clutch and the follower preview](#the-clutch-and-the-follower-preview).

Two calibrations, and they are different in kind. `cpp/frames.hpp` is a
*convention* fixed by two specs and cannot be wrong at runtime.
`_QUAT_HAND_FROM_GHOST` / `_POS_HAND_FROM_GHOST` in `app.py` are a *measurement*
of how a hand holds a tool, taken on a headset and checkable nowhere else. See
[Frames](#frames-cppframeshpp).

## Build

**This example is its own wheel, and the wheel is the only way to run it.**

```bash
uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/   # THIS checkout, not PyPI
uv pip install ./examples/mujoco_xr                                    # same environment
python -m isaacteleop_examples.mujoco_xr                               # needs a headset
```

Both wheels must land in **one** environment, and that is the environment
[`rigs/mujoco_xr.yaml`](../../rigs/mujoco_xr.yaml) runs from. `uv pip install`
compiles the extension through scikit-build-core and does not read the CMake
build tree at all.

You need `uv`, CMake ≥ 3.20, a C++ compiler, CUDA, and the OpenGL headers
(`libgl-dev` on Debian/Ubuntu — `cuda_gl_interop.h` includes `<GL/gl.h>`
unconditionally, so this is CUDA's requirement as much as ours). No Vulkan and
no `glslangValidator`: the readback shader is a string the driver compiles at
runtime. Nothing is *linked* against OpenGL either — `cpp/gl.hpp` takes the
enums and the `PFNGL...PROC` typedefs from `<GL/glcorearb.h>`, which declares no
symbol, and resolves the 45 entry points in `cpp/gl_functions.inc` through the
platform `GetProcAddress` against the context `mujoco.GLContext` created.
Running the app additionally needs a GPU with EGL + CUDA and a headset. **Build
isolation does not cover the non-Python half of that list**: on a host missing
CUDA or the GL headers the install fails *inside* the isolated PEP-517 build,
with the CMake or compiler error wrapped in backend output.

**On a multi-GPU host, set `MUJOCO_EGL_DEVICE_ID`.** The OpenGL context has to
land on the same card viz picked, and nothing makes that happen by default —
`MUJOCO_EGL_DEVICE_ID` indexes EGL devices, which need not agree with CUDA's
ordering. The renderer checks at construction and names both device numbers
rather than render into the wrong card's memory.

**`pip install -e` is not supported.** An editable install redirects the package
back to the source tree, which is exactly where the in-tree CMake build drops
*its* `_mujoco_xr*.so` — you would silently import that one instead, and the
wrong `.so` imports fine right up until `mjModel*` crosses the boundary. To
iterate, `uv pip install --reinstall-package isaacteleop-examples-mujoco-xr
./examples/mujoco_xr` (the CMake cache persists via `build-dir`, so it stays
incremental). `--reinstall-package` rather than a bare reinstall because the
version is fixed at `0.0.0`, so `uv` would otherwise skip the rebuild.

### The in-tree CMake build, which is a separate thing

The example is **also** wired into the root build, and that path is what
[`ctest`](#tests) runs against: it builds `_mujoco_xr*.so` in place beside
`python/isaacteleop_examples/mujoco_xr/__init__.py` and installs nothing.

So the extension is compiled twice — once here for `ctest`, once by
scikit-build-core for the wheel, whose ABI tag comes from whichever interpreter
installs it. That is a deliberate trade: collapsing it means either shipping the
root build's tree as a wheel with no ABI tag, or dropping the in-tree `ctest`
path. It collapses for real the day `ctest` runs against the *installed* wheel,
which needs a locally published `isaacteleop` to resolve against — the one on
PyPI is a different build from the viz in this checkout.

Steps 1 and 3 are the same command, and the repetition is not decorative: on a
fresh clone the interpreter in step 2 does not exist until configure creates it,
and **the mujoco probe runs at configure time**, so it has to run again once the
wheel is there.

```bash
# 1. Configure once to create the build venv. This first pass necessarily
#    reports `-- mujoco_xr: skipped ...` — expected, not a failure.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 2. Install mujoco into the interpreter configure just created. `python -m pip`
#    does not work: that venv has no pip.
uv pip install --python build/cmake-cpython-312/teleop_build_venv/bin/python "mujoco==3.11.0"

# 3. Re-configure. NOW the probe finds mujoco and the example is added.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 4. Build. There is no `cmake --install` step for this example.
cmake --build --preset py3.12 --parallel
```

A green build does **not** mean this example compiled. The reliable check:

```bash
cmake --preset py3.12 -DBUILD_VIZ=ON 2>&1 | grep '^-- mujoco_xr:'
```

The `ON` line names the exact `libmujoco.so.*` that was linked. There is no
`BUILD_EXAMPLE_MUJOCO_XR` flag — the gate is `BUILD_VIZ` plus whether `mujoco`
is importable from the interpreter CMake resolved.

**The same trap applies to the ctest list.** `tests/CMakeLists.txt` globs
`test_*.py` at configure time, so adding or deleting a test file leaves the
entry list stale until you re-run step 3.

## Run

```bash
python -m isaacteleop_examples.mujoco_xr --help   # includes CloudXRLauncher's flags
```

Through the rig, which starts the CloudXR runtime alongside the app, from the
repository root:

```bash
python -m isaacteleop.rig rigs/mujoco_xr.yaml
```

`{python}` in the rig expands to the interpreter you launch it with, so both
wheels have to be installed *there* — not in the build venv, which has no
`isaacteleop`. Picking up the wrong venv is silent, so check before you start:

```bash
python -c "import sys, isaacteleop; from isaacteleop_examples import mujoco_xr; print(sys.executable, isaacteleop.__file__, mujoco_xr.__file__)"
```

Both packages must come from the same `site-packages`; the app's startup log
prints the `isaacteleop:` line for the same reason. Against a runtime you
started yourself:

```bash
python -m isaacteleop.cloudxr --accept-eula                                    # one terminal
python -m isaacteleop_examples.mujoco_xr --no-launch-cloudxr-runtime           # another
```

`--no-launch-cloudxr-runtime` is not cosmetic: omitting it makes the app start
its own runtime, which is right when nothing else has and fatal when something
has (the runtime is a host singleton on WSS port 48322). If no runtime is
running and you pass it anyway, the failure comes out of `VizSession.create` as
an OpenXR error before any of this example's code runs — **no `[mujoco_xr]`
lines at all** is the tell.

There is one scene and no flag to change it: `assets/scene.xml` is package data
beside the module, and editing it is how you load something else. There is no
desktop or headless display mode; without a headset the verification path is
[`ctest -L mujoco_xr`](#tests).

## The harness the ghost renders

The ghost's pose comes from an `EePoseRateLimiter` (`harness.py`,
`_build_pipeline()`), so what the operator sees is **the command a follower
would execute**, not where their hand is. That is the point:
[#738](https://github.com/NVIDIA/IsaacTeleop/issues/738) reports operators
losing minutes to harness interventions they could not perceive — the arm "stops
following", and the instinct that produces (push harder, move faster) is exactly
wrong.

The limiter is a three-band governor: motion under the limits passes through
untouched, motion over them is clamped to the limit, and a frame whose input
velocity breaks the reject envelope is refused outright. Two things report which
band is live:

- **The ghost lags the hand.** Proprioceptive, and free — you feel where your
  hand is and see the tool is not there.
- **The ghost changes colour.** Amber while clamping, red while rejecting,
  authored blue while passing through. Categorical, which the lag alone is not:
  a clamp and a refusal both read as "behind my hand".

Colour is written to the shared `leader_ghost` **material**, so one write
recolours the whole tool. Do not switch it to `geom_rgba`: that silently wins
over the material, and the four geoms would then have to be kept in step by
hand. Alpha stays 1.0 in every band —
`assets/leader/leader_gripper.xml` explains what opacity buys, and a translucent
"intervening" state would quietly take those risks back.

`InterventionMonitor` recovers the band by comparing what the limiter was handed
against what it emitted, rather than by asking the limiter. That keeps the
shipped node unmodified and works for any governor with the same contract; the
cost is one extra `OutputCombiner` key (`COMMANDED_POSE_KEY`) carrying the
limiter's own input, which nothing draws.

**The limits are chosen for this demo, not measured against an SO-101.** 0.5 m/s
and 2.5 rad/s clamp, 2.0 m/s and 10 rad/s reject — set so ordinary reaching is
pass-through and a deliberate flick trips both bands on demand.
`RateLimiterConfig` itself defaults to 0.25 m/s, which is the more conservative
bring-up value and would clamp during ordinary reaching. **Nothing tests these
numbers**, so retuning `_HARNESS` past what a hand can reach silently produces a
demo that never intervenes.

**The jaw is ungoverned** — a `JointRateLimiter` would bound it, but the trigger
is one scalar the operator drives directly, not a solved output that can diverge.

While the clutch is disengaged the limiter is still running, on a commanded pose
that tracks the follower. That is not idling: the gate below refuses to go green
unless the limiter is in its pass-through band, so this is where that conjunct
gets its evidence.

`rate_limiter.py` is
[#727](https://github.com/NVIDIA/IsaacTeleop/pull/727) rehomed from
`src/retargeters/` to `src/python/isaacteleop/retargeters/`, which is where that
package now lives.

## The clutch and the follower preview

Disengaged, the operator drives the **follower's** gripper, and two things move
it independently:

- **Position** is the controller's, all three axes — `follower.py` slides the
  whole arm so its **jaw** tracks the hand every frame, the grip offset off it
  *exactly*.
- **Yaw** is the controller's own yaw, every frame, with no button held. The base
  turns onto it and the arm swings around the jaw.

**The joints are locked.** `qpos` is written once, to `Q_HOME`, and the arm is
moved as a rigid body — `Follower._place` is the one writer of `body_quat`,
`Follower._move_base` the one writer of `body_pos` — so the gripper's orientation
*in the base's frame* is a constant, and the jaw lands at its offset from the hand
with no residual and no point it cannot reach. The offset starts at
`GRIP_FROM_CONTROLLER_XR`: level with the hand laterally, 0.25 m ahead and 0.10 m
below it, so they can see an arm they are not standing inside.

**Both channels land on `GRIPPER_SITE`, and that is what makes the yaw pivot
right.** Upstream declares a `gripperframe` site on the `gripper` body 98.4 mm out
from its origin, 3.8 mm off the closed jaw surface — where a grasped object would
be. The arm is placed *by* that point, so it is also the axis the yaw turns about:
the jaw holds still and the base swings around it, 273 mm across ±90° of yaw.
Place by the gripper **body** instead and the pinned point sits 98.4 mm short of
the jaw, which then orbits it — a 15.8 mm arc over that same sweep, on the one
point the operator is actually aiming. The body frame is still the **orientation**
carrier, and `Follower.gripper_pose_mj()` returns it for exactly that; do not read
its position as the tool point.

**That offset is tunable from the headset, and only while disengaged.** The right
thumbstick walks its two horizontal terms — stick X left/right, stick Y
forward/back, forward sending the arm further out — at 0.20 m/s of full
deflection, past a 0.15 deadzone and clamped to ±0.60 m on each. Deflection is a
*rate*, so the offset holds where the stick left it; the drop below the hand is
not on the stick. Both terms are carried on the **controller's own facing**, so
forward sends the arm further along the pointing ray and right sends it to the
controller's right — and yawing the controller carries the arm around with it at a
fixed relative position, rather than leaving it behind in the world. Note this is
the *facing*, not the base yaw, which leads it by the measured bias and would send
"forward" off by exactly that much. Let go and the app prints what it settled on,
in the constant's own form:

```
follower:   offset tuned to GRIP_FROM_CONTROLLER_XR = np.array([-0.31, -0.10, -0.22])
```

**Paste that back into `follower.py` as the new default.** It is a headset
judgement and no headless test can make it, so this is how a session becomes a
constant rather than a note-to-self. B (`SECONDARY_CLICK`) puts it back to the
authored value on its rising edge, for an offset walked out to its clamp or a
drifting stick that got there on its own. `ENGAGED` neither the stick nor the
button does anything visible: the arm is hidden and frozen there, and an offset
moving under it would apply the whole excursion on the release frame.

Squeeze while the arm is **green** and the follower vanishes, the leader appears
**in the hand** at the follower's rotation, and the harness colouring above takes
over. **The offset is the preview's alone.** The leader is the tool the operator
teleoperates, so it is mapped 1:1 onto the controller and an engagement does not
inherit it — tuned or not. The visible cost is that the engage frame swaps one
tool for another a whole offset away — a handoff between two objects, not one
object jumping.

Release and the follower comes back **immediately**: the arm is drawn again on
the release frame itself and the drag resumes on that same frame, so the
controller is driving it again with nothing in between.

**Do not put a smoothstep back to the home pose on the release.** The drag runs on
every disengaged frame, so a ramp has nothing to do: the arm would reach home and
be dragged straight back onto the hand on the next frame. The visible cost of not
having one is real and accepted — the arm teleports from where it froze onto the
hand's position and yaw, by however far the operator moved and turned during the
engagement.

**The dwell is therefore the whole post-release debounce.** The gate's phase
conjunct holds it shut for the entire engagement, so `_dwell_s` restarts at the
release and no squeeze can re-latch for ~8 frames. Nothing else gates it: the
limiter's reset pulse absorbs the teleport in one frame, so `still catching up`
does not fire.

**The app drives from the `aim` pose, and `HAND_POSE` is the single constant that
says so.** OpenXR publishes two controller poses for two different jobs.
`grip` is the palm centroid, published so an application can render an object the
user is *holding*; its `-Z` runs little finger to thumb, **up through the fist**,
and is not a pointing direction at all. `aim` is published so an application can
*point*: its `-Z` is the ray. Reading a facing off `grip` therefore turns 1:1 with
the hand but has an arbitrary zero — a fixed yaw offset the operator sees and
cannot tune away — which is why this app moved to `aim`.

`HAND_POSE` reaches everything: the follower's drive, the engage gate's operand,
the clutch's latched home and the ghost's placement, because they all consume the
one `HAND_POSE_KEY` channel. `SO101ClutchRetargeter` reads the controller group
directly rather than that channel, so it takes a matching `controller_pose=`
argument; its *orientation* delta is provably invariant to the choice — for a fixed
body-frame `T`, `(R·T)(R₀·T)⁻¹ == R·R₀⁻¹` — so that argument changes the
translation pivot only.

**The cost is real and is the thing to watch in a headset.** `aim`'s *origin* is a
device-specific ray origin rather than the palm centroid, so the arm's position
gains a lever arm that swings as the wrist turns. Flip `HAND_POSE` back to
`HandPose.GRIP` to compare — but re-tune `_EULER_HAND_FROM_GHOST_DEG` when you do,
because the ghost calibration is relative to whichever frame that constant names.

**Which axis you read was a leakage budget on `grip`; on `aim` there is nothing to
choose**, since `-Z` is the ray by definition. The measurement is kept because it
is what rules `grip` out and what to re-run if `aim` disappoints. Every candidate
turns 1:1 with a rotation about the world vertical — an axis' azimuth does that by
construction — so what separated them is only how much wrist **roll and pitch bleed
into the arm's yaw**. Each axis is blind to rotation about *itself* and sensitive to
the rest. Worst leak over ±45° at the posture the gate demands, measured on `grip`:

| motion | `-Z` thumb | tool/barrel | flattened | best-fit |
|---|---|---|---|---|
| roll about the thumb axis | **0.00** | 12.89 | 21.09 | 23.40 |
| roll about the barrel | 11.75 | **0.00** | 29.60 | 31.94 |
| pitch about grip `+X` | **0.00** | 27.88 | 0.41 | **0.00** |
| pitch about horizontal-perp | 2.30 | **0.00** | **0.00** | **0.00** |

On `grip` the thumb axis won that table — best worst case, exact on two of four.
`aim`'s `-Z` is the **tool/barrel** column, whose leak is dominated by how far the
axis sits from horizontal at the posture held; the 27.88° there is a near-vertical
singularity reached only because that stand-in axis starts 43.7° up, and a real aim
ray held level does not go near it. **That is an expectation, not a measurement** —
the grip-to-aim transform is per-device and no headless test here can supply it, so
re-measure the leak on a headset. `follower.yaw_of_axis` takes the axis as a
**required** argument for exactly this reason; `follower.yaw_of` keeps `-Z` and is
for the **head** alone, whose `-Z` genuinely is its view direction.

**`_YAW_TRIM_DEG` should now be zero, and a session that needs a large one is
evidence, not a knob.** Removing the offset is the whole reason for reading `aim`,
so if a trim is still needed the switch did not do its job. It is kept only to
absorb a runtime whose aim convention differs from the operator's expectation.
**Hold A and push the right thumbstick** left or right at 20°/s; A owns the stick
while held, so a trim cannot also walk the grip offset. Let go and the app prints
it in the constant's own form, to paste back:

```
follower:   yaw trim -> _YAW_TRIM_DEG = -10.0
```

It is applied as a **constant** on top of the reading, so it cannot introduce
leakage of its own.

**The ghost calibration's two halves are now sourced differently, and that is the
point.**

Its **rotation**, `_EULER_HAND_FROM_GHOST_DEG`, is **solved, not measured**. Nothing
in it is a free choice once you decide what posture the engage gate should ask for,
and *that* is the thing worth choosing. On `aim` a pose's `-Z` is the pointing ray,
so demanding "level and unrolled" means "hold the controller the way you would
naturally point it". `(270, 0, 90)` produces exactly that — **0.00° of pitch and
0.00° of roll** against `Q_HOME`. It is a consequence of `Q_HOME`, so re-solve when
that moves: it is the gripper's `xquat` at `Q_HOME` and base yaw 0, carried into XR by
`_xr_from_mj_quat`, as intrinsic-XYZ Euler.

Getting it wrong is quiet, and porting a `grip`-measured value is how it went wrong
before: ported from that frame, it
demanded **30° of upward pitch** — invisible on `grip`, where `-Z` is the thumb axis
and points up anyway, and immediately obvious on `aim`, where it means aiming at the
ceiling. Bearing is deliberately unpinned, hence the rounding to whole degrees: the
base tracks the hand's yaw, so the gate's yaw cancels and `base_yaw_bias` absorbs the
2.8° that is left.

Its **translation**, `_POS_HAND_FROM_GHOST`, stays a headset measurement — no posture
pins it — and the shipped value was measured on `grip`. That port *is* per-device, so
`_log_hand_frames` computes it from one frame with both poses valid and prints it:

```
hand frames: this device's aim pose sits 50 deg and 40 mm off its grip pose. HAND_POSE is AIM, so for the ghost to sit where it did on GRIP, its POSITION wants:
hand frames:   _POS_HAND_FROM_GHOST = np.array((-0.000, 0.020, 0.015))
```

Both terms of that port are needed — the origins' separation *and* the old offset
turned by the same rotation; dropping the second leaves the ghost centimetres out
while its orientation looks perfect.

**The base leads the hand by a measured bias so the JAW faces it.**
`Follower.jaw_yaw_xr` reads `GRIPPER_SITE`'s `+Z` — which way the gripper is turned
— and `base_yaw_bias()` measures the lead at startup rather than authoring it,
because how far the jaw sits off its own base yaw follows from `Q_HOME` and
upstream's chain. With `J5 = -90` it comes out at **92.79°**. The jaw then faces the
controller to **0.000° at every world yaw**, with **0.00° of leak from wrist roll
and 0.00° from pitch**.

The jaw and the arm's *reach* are different axes, parting company by exactly J5's
roll: J5 turns the gripper about its tool axis without moving the links, so aiming
one leaves the other off by that much. Aiming the jaw is the choice here, and the
cost is the arm's body sitting **92.79°** to the side of where you point. The two
are coupled through the calibration — moving the bias moves the demanded posture
with it — so `_EULER_HAND_FROM_GHOST_DEG` must be re-solved whenever the aimed axis
or `Q_HOME` changes.

**The arm's yaw cancels the hand's, and that is why no button locks one.** The
gate compares the controller against the rotation the clutch would latch, and
because the base carries the wrist's own yaw that rotation is `wrist_yaw ∘ C` for
a session constant `C`. The geodesic angle between them is therefore the angle
between the wrist's *pitch and roll* and `C` — the same number whichever way the
operator faces and whichever way they point. One posture to learn rather than one
per reach, and `Q_HOME` earns its derivation from exactly that: the gripper
orientation it produces is what the gate asks for. Correcting the yaw drive also
drained `C` of nearly all its own yaw — from 2.79° to 0.73° — so the posture the
gate demands no longer asks the operator to hold their wrist turned off the
direction they are pointing.

### Where the arm goes

**Against the measured head pose, not the reference-space origin.** On the first
frame carrying a usable `info.views[0].pose`, the home grip is placed
`HOME_GRIP_FROM_HEAD_XR` — 0.30 m below and 0.60 m in front — of the head,
**yaw-projected** onto the head's facing so "in front" means in front of the
operator and not along the reference space's `-Z`. Yaw only: a bowed or tilted
head must not tip the arm toward the floor.

**The anchor is a starting pose and nothing more.** Its *position* is only where
the arm waits out the window between the first head pose and the first controller
frame; its *yaw* only turns the arm to face the operator for that same window.
From the first driven frame the controller owns everything — position, base yaw,
and the frame the thumbstick offset is carried on. `Follower.base_yaw_xr` reports
whichever yaw is actually on the base.

The app does not get to choose its reference origin. viz asks for no
floor-origin space, so a runtime that hands back a stage-origin one puts
everything authored against that origin a standing height out — which is what a
headset run showed. The head pose is the only datum the app can trust.

The anchor does not follow the head afterwards either: the pose the clutch is
about to latch must not move out from under the operator as they look around.

Placement is therefore runtime-derived, and so **neither tool is drawn until the
anchor exists**. `Follower.__init__` starts the arm hidden, `_Preview.__init__`
starts the ghost hidden, and `_Preview.after_step` returns early while
`arm.anchored` is false — with the gate held shut, so the clutch cannot latch
onto a pose the arm never held either.

Two phases — `DISENGAGED` and `ENGAGED` — and the enum never answers "is the
clutch latched?". `SO101ClutchRetargeter.is_engaged` is the sole authority for
that; the phase takes it as an input every frame and never copies it into a
field.

**Green means all three of these hold**, and `follower.py`'s gate returns every
one that does not, which `app.py` logs on each transition:

- the hand's rotation is within the enter band of the rotation the clutch would
  latch,
- the rate limiter is passing through, not clamping,
- and all of that has held for a dwell.

**There is no reach conjunct, and no reach envelope.** The rigid drag puts the
gripper exactly at its offset from the hand every frame, so a position residual
is identically zero and a limit on it would forbid nothing — the arm goes
wherever the hand goes, including places no articulated SO-101 could reach.
`EngageGate.evaluate` says so where the conjunct used to be; do not add one back
believing it keeps the operator inside a workspace this preview does not have.

The rotation conjunct is the whole point. The leader is rebased onto the
follower's rotation at engage, so if the operator's wrist is 40° from where the
follower's gripper is pointing, that 40° does not go away — the clutch composes
orientation as a **delta**, so it persists for the entire engagement. Hysteresis
and the
dwell are not polish either: the angle is recomputed every frame from a noisy
controller, and a colour strobing at 72 Hz in a headset is worse than a wrong
colour.

**The pass-through conjunct is not optional.** The leader renders the *limiter's*
output. The grip calibration converts hand rotation into ~4°/cm of tool motion,
so 0.5 m/s of hand speed is 3.49 rad/s against a 2.5 rad/s clamp: clamping starts
around 0.36 m/s, which is ordinary dragging. Without this conjunct the arm goes
green while the tool about to be revealed is tens of degrees and hundreds of
milliseconds behind.

**The handoff is exact, and that is measurable.** `app.py` pushes
`clutch.set_home_base_T_ee(pose_from_ghost_body(...))` on every non-`ENGAGED`
frame, built from **two different sources**: the position from the last usable
hand pose — latched in `after_step`, because `before_step` runs a frame ahead of
it — and the rotation from the follower's gripper. So the clutch's home is the
hand's position at the follower's rotation, and on the latch frame it emits that
home exactly. Neither half is interchangeable: latching the gripper's *position*
would carry the preview's offset into an engagement the clutch composes as a
delta, and taking the *rotation* from the hand would leave the gate's rotation
conjunct demanding nothing. `MEASURED_BASE_T_EE_INPUT` is deliberately left unwired — `_latch`
reads it for **position only** and always takes the rotation from the last
commanded rotation, so it cannot deliver this.

Which is also the trap. Because the grip calibration **cancels exactly** through
the handoff, the leader lands in the hand at the follower's rotation for *any*
value of it and every geometric test passes. Its one surviving effect is which
wrist posture the gate demands, so `app.py` logs two readable directions at
startup — where the tool points and where the gate wants the operator's thumb —
and **warns** past 45° on the thumb. It does not refuse to start: this app is the
only place the calibration can be judged, so aborting would prevent the
inspection the log exists for.

Read the **hand-axis** direction when judging `_EULER_HAND_FROM_GHOST_DEG` — the log names it `pointing` on `aim` and `thumb` on `grip`. The tool
direction does not contain the calibration at all — it is a guard on `Q_HOME` and
a mesh refresh, and it reads the same 15° for a calibration that is right and one
that is 118° wrong. Both are reported in the **arm's own frame** — XR axes
un-yawed by `base_yaw_xr` — so they read the same whichever way the operator was
facing and however they hold their wrist, which is also why the log can run
*before* the arm is anchored.
Against the reference space's `-Z` they would just report where the operator
happened to stand.

**Nothing integrates.** `mj_step` is never called: the follower is slid by its
base and read back through `mj_forward`, and the ghost is two mocap bodies.
Upstream's six `position` actuators are therefore inert — with `ctrl = 0` and
`mj_step` they would drag the arm back to `qpos0` at about 1 rad per 0.4 s. There
are deliberately no `gravity="0 0 0"` or `<flag actuation="disable"/>` attributes
in `scene.xml`: flags that suppress dynamics nobody runs tell the next reader
that dynamics run. The invariant that replaces them is simply *`qpos` is written
once, by `follower.py`, and `body_pos` only by `Follower._move_base`*.

With no `mj_step` there is also nothing left to refresh derived state, so the
second invariant is the pass `mj_step` used to supply for free: **one
`mj_forward` after every `qpos`, `body_pos` *or* `mocap_*` write, before every
`xpos` / `xquat` / `geom_xpos` read — including the read inside
`mjv_updateScene`.** `mocap_pos`/`mocap_quat` are *inputs to* forward kinematics
and the renderer draws `geom_xpos`, so a correct mocap row is not a drawn pose.
`follower.py` owns that call for the arm and `_Preview.after_step` for the ghost;
nothing while `ENGAGED` moves the arm, which is why the ghost cannot borrow the
drag's.

`SO101ClutchRetargeter` gains one input for this, `ENGAGE_PERMITTED_INPUT`: an
`OptionalType` boolean checked **only** where a latch is owed, so it gates the
latch and never the engagement, and absent or unwired means permitted. It is an
enable precondition, not a safety-rated stop.

## Conventions you can break

### Frames (`cpp/frames.hpp`)

`R_mj_from_xr = Rz(-90) * Rx(+90)`. XR `-Z` → MuJoCo `+x`, XR `+Y` → MuJoCo
`+z`, XR `+X` → MuJoCo `-y`. Testable definition: a point 1 m in front of the
operator at eye height `h` lands at MuJoCo `(+1, 0, h)` before the workspace
translation. `tests/test_frames.py` checks exactly that. It deliberately differs
from `examples/cloudxr_mujoco_teleop/visualize_poses_mujoco_example.py`, which
applies `Rx(+90)` only (XR-forward → MuJoCo `+y`, not REP-103).

**`kTransMjFromXr` is the lever, and it is a calibration that is routinely
wrong.** `(-1.0, 0.0, -0.73)`, two independent terms: `x` is operator standoff
(the base sits ~1 m in front of the operator), `z` is a floor datum — MuJoCo
`z = 0` is a work surface 0.73 m above the physical floor. That `z` is only
right against a floor-origin reference space, and the session does not ask for
one: viz's default origin is the headset's start pose, i.e. head height. A
scene that puts static content on the work surface owns re-tuning it.
**Neither term may be zeroed.**

It places static content only. The ghost goes out through `mj_from_xr` and the
eye pose goes out through the same transform, so both constants cancel on it and
the shipped scene — which is the ghost and nothing else — is blind to a wrong
value. Judging one means a scene with something world-locked in it.

There is no recentre keypress and no runtime override: changing the datum means
editing the constant and rebuilding (~8 s). The procedure is to stand where you
intend to work, start the app on such a scene, read the `frames:` line in the
startup log, compare the virtual surface against the real one, and adjust `z`. A
`--workspace-offset` flag was considered and rejected: a Python-side offset
applied to one of the two conversions and not the other would move the gripper
and leave the scene put, which is precisely the symptom this example exists to
disambiguate.

### Where the ghost sits on the hand (`app.py`)

A *second* calibration, and a different kind: `_EULER_HAND_FROM_GHOST_DEG` and
`_POS_HAND_FROM_GHOST` place the leader gripper on the operator's hand. Without
them the gripper's body origin — the follower's `gripper` datum, up at the wrist
— lands on the grip pose, so the tool hangs off the hand at an arbitrary angle.

**These are measured on a headset, not derived.** That is the whole provenance:
it is a claim about how a gripper should look in a hand that is actually holding
a *controller*, and nothing headless can settle it.

A mesh-derived version was tried first and hardware overruled it. It mapped the
handle loop's principal axis onto the fist axis, the loop's centroid onto the
palm, and the jaw assembly forward of the knuckles — i.e. it assumed the hand
goes *through* the loop, the way it would on the real leader device. Measured
against the shipped values, that model puts the loop centroid 56 mm from the
palm and not straddling it at all. The premise was wrong: you are gripping a
controller, so where the loop falls is a question about the controller in the
hand, not about the loop.

The mesh geometry is still worth knowing when reading the numbers.
`Handle_SO101` is a closed **loop**, not a bar; the jaw assembly sits off to one
side of it, and the jaws run **60.7°** off the loop's long axis. The OpenXR
**grip** frame they are expressed in (`grip/pose`, not `aim/pose`) is `−Z` little
finger → thumb, `+X` into the palm, `+Y` forward through the knuckles.

**To re-tune.** The rotation is degrees, intrinsic X-then-Y-then-Z — the same
convention as a MuJoCo `euler=` attribute, pinned by a test against a compiled
model rather than asserted here. Change one angle, `uv pip install
--reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr`,
relaunch: `Rz` spins the gripper about its own long axis, `Rx` / `Ry` tilt it in
the hand, and `_POS_HAND_FROM_GHOST` slides it along the hand-pose axes if the angle
is right but the placement is not. **No test asserts a posture**, deliberately —
they cover the machinery, so re-tuning cannot turn them red. The one that
matters asserts the ghost is *rigidly attached* to the grip frame, which is
true of any calibration and false if the correction is composed on the wrong
side.

**A trap worth keeping even though the derivation is retired.** MuJoCo rewrites
every mesh into its inertial frame, so recovering an STL's own axes needs
`mesh_pos` / `mesh_quat`. Skip that and you get the *handle's* axis back instead
of the jaws', which is self-consistent, passes an axis-only check, and is wrong
by 60°. The shank's own principal axis is no substitute either — it is a
near-isotropic blob (σ₀/σ₁ = 1.26), so its principal direction is noise.

### Scene assets

Every geom type draws, and the XML's materials, lights, shadows and
reflections are live — this is `mjr_render`, so the scene file means what the
MuJoCo docs say it means.

**The lighting knob that matters is ambient, not diffuse.** `scene.xml` sets
`<visual><headlight ambient="0.4 0.4 0.4" diffuse="0.4 0.4 0.4"
specular="0.3 0.3 0.3"/>`. Ambient is direction-independent, so it is a *floor*
on how dark a surface can get; diffuse is what carries shape. MuJoCo's own
defaults are why this scene read as dark — not because they are dim overall, but
because the floor under them is 0.1. Measured over the ghost from three
directions, as a share of its material albedo:

| headlight (amb / diff / spec) | shades | dimmest | mean | below ⅓ albedo | above albedo |
|---|---|---|---|---|---|
| `0.1 / 0.4 / 0.5` (MuJoCo default) | 437 | 0.10 | 0.25 | **94.0%** | 0% |
| `0.4 / 0.4 / 0.3` (shipped) | 372 | **0.40** | 0.55 | 0% | 0% |

The trade is explicit: the shipped values give up some tonal range — 372
distinct shades against the default's 437 — to buy a hard floor. The dimmest
pixel is 0.40 of albedo, which is the ambient term exactly.

That floor earns its keep twice over. It bounds MuJoCo's smeared crease normals
— one averaged normal per welded vertex, and `render_gl3.c` lights one-sided, so
a face corner pointing away from its own triangle (11.4% of them on
`wrist_roll`) lands on ambient rather than on black, which is a tonal wobble
instead of shattered facets. And it bounds shadows the same way, so
`mjRND_SHADOW` needs no attention.

Specular is the one term that spends *outside* that budget: it is additive and
white rather than scaled by the material `rgba`, and it is gated by the material
as much as the light — `leader_gripper.xml` declares neither `specular` nor
`shininess`, so MuJoCo's defaults (0.5 and 0.5) apply and the effective highlight
is `0.3 × 0.5`. Ambient plus diffuse comes to 0.8, and that 0.2 of headroom is
what absorbs it: no pixel exceeds the albedo at these values. Raising either
term without lowering the other is what would start clipping.

**The remaining defect: the headlight is not head-mounted here.**
`mjv_updateScene` bakes it into `mjvScene.lights[0]` from the `mjvCamera` it is
passed, and this app passes a fixed `mjv_defaultFreeCamera` and only overwrites
`mjvScene.camera` afterwards. It is a directional light fixed in MuJoCo world by
`model.vis.global_.azimuth` / `elevation`, and it never follows the head. The
ambient floor makes that survivable rather than correct — the ghost stays legible
at every hand orientation, but which side of it is lit depends on where in the
room the hand is, not on where the operator is looking. Two ways to fix it
properly: write `mjvScene.lights[]` in `render()` after the cameras (`mjr_render`
reads the array as you leave it, and `dir` is the camera's `forward`, un-negated
— that measures 0.71 mean against the 0.55 above, and independent of hand pose),
or give the scene its own `<light>` elements, which `mjv_updateScene` does place
correctly.

The 17 STLs are **fetched, not vendored** — 18 MB of binary in a source tree is
a poor trade when upstream publishes them at a stable commit, and Git LFS made
every clone pay for them. Run it once, then reinstall, because they are package
data:

```bash
examples/mujoco_xr/scripts/fetch-so-arm.sh          # from the repository root
uv pip install --reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr
```

Nothing fetches at build time: an isolated PEP-517 wheel build must not reach
the network, so the app fails at startup naming the script and `test_ghost.py`
**skips** with the same reason. Downloads are checksum-verified against a pinned
commit — a silently substituted mesh renders as a broken gripper rather than an
error, which has already cost a debugging session.

Each entry names its own destination: the two tools are separate MJCF fragments
in separate directories, and each resolves meshes against its own, so
`sts3215_03a_v1.stl` is fetched **twice** rather than aliased across. Both sets
land **flat** beside their fragment — MuJoCo drops an included file's own
`meshdir`, so upstream's `meshdir="assets"` is inert once included.

The follower's MJCF is upstream's own `so101_new_calib.xml`, fetched verbatim and
never edited; `assets/follower/follower_arm.xml` is a tracked wrapper — one
material and an `<include>`, under a provenance comment. (`joints_properties.xml` is
deliberately not fetched: upstream inlines its `<default>` block rather than
`<include>`ing it, so the file is never read.)

The script also pulls `so101_new_calib.urdf`, which is where the trigger's hinge
and its 0..100° travel come from, so it is on disk to check them against. Three of
the leader's four meshes are leader-specific print parts; the fourth is the
**STS3215 servo**, shared with the follower. It is not decoration — `wrist_roll` is a C-shaped
bracket that wraps the servo, so without it the assembly has an open notch where
the motor belongs and reads as a broken asset.

It declares **two** mocap bodies — the gripper and its trigger — because the
trigger articulates. A mocap body must be a jointless child of the world, so the
trigger cannot be a hinged child of the gripper: its angle would live in `qpos`,
which nothing here writes — this app never calls `mj_step` and drives the ghost
through `mocap_*` alone — so the jaw would never swing.

The ghost is **opaque**, and `test_ghost.py` asserts it. That removes the
draw-order constraint (at alpha 1.0 the depth test decides everything) and the
ghost-writes-depth-into-the-reprojection-buffer concern. This scene **does** now
put a robot under the ghost — the follower — so opacity is the only thing still
holding both off. `scene.xml` already `<include>`s the leader **last**, which is
the order the draw would need (`mjv_updateScene` emits in geom-id order), but
nothing asserts it: the assertion belongs with the first scene that drops the
alpha back.

**Pass MuJoCo an absolute scene path.** Measured on mujoco 3.11.0, a *relative*
model path mis-composes an `<include>`d file's paths and fails with
`Error opening file '<a path that exists>'` — with the follower's nested include
it composes the directory onto itself and opens `<dir>/<dir>/so101_new_calib.xml`.
`DEFAULT_SCENE` in `app.py` is absolute for this reason.

**Visibility is `model.geom_group`, from Python.** Group 2 draws and group 3 does
not (`mjv_defaultOption`), so hiding a tool is one write to a slice of
`geom_group`. A hidden geom never becomes an `mjvGeom`, so it never reaches the
draw loop and never writes depth — which is why this is a group switch and not an
alpha. No C++ renderer change is needed or wanted for it.

## Tests

```bash
ctest --test-dir build/cmake-cpython-312 -L mujoco_xr --output-on-failure
```

| file | covers |
|---|---|
| `test_frames.py` | the XR→MuJoCo axis map and quaternion order |
| `test_projection.py` | the mjvGLCamera frustum (that it is the fov projected onto the near plane, and that the half-width is set so mjr_render's aspect fallback stays off) and the standard-Z depth contract |
| `test_app_helpers.py` | the NaN-safe `dt` clamp, the zeroed-`predicted_display_time` guard, and that the first-frame frustum assertion passes on the real thing and fires on each way it can go wrong |
| `test_readback.py` | **the GPU path**: that something is drawn at all, that row 0 is the top of the operator's view and the image is not mirrored, that the depth handed to `submit()` is standard Z with the background at exactly 1.0, and that the two eyes carry parallax of the right sign. Skips with a reason when there is no GPU |
| `test_ghost.py` | the overlay: that the ghost is opaque, collision-free and carries no mass, that both its bodies are kinematic mocap bodies with no joint anywhere, that the four leader parts form one assembly with sub-mm gaps at the bolted joints and the servo seated in its bracket, that the print STLs are scaled from millimetres and the servo is not, that the ghost is *rigidly attached* to the grip frame whatever the calibration, that squeezing swings the trigger monotonically from the URDF joint's upper limit to its authored zero without driving the lever through the body, that the shipped `SO101GripperRetargeter` really is the thing driving that channel (built as a real pipeline and fed synthetic DeviceIO snapshots), and that an untracked controller freezes the whole gripper rather than parking it at the scene origin |

All but `test_readback.py` run on a CPU with no GPU, no headset, no CloudXR
runtime and no window system; keep it that way, because a permanently-skipping
test reports green while covering nothing. `test_readback.py` is the deliberate
exception: what it covers is otherwise invisible until someone is wearing a
headset, and it needs no headset itself.

## Not verified anywhere in CI or on a developer desktop

**Everything downstream of the readback.** `ProjectionLayer.submit()`, the
frame loop that sequences it, OpenXR session sharing via `oxr_handles`, whether
the runtime accepts the depth layer, and **controllers on a shared session** —
none of it is executed by any test or on any machine here. `test_readback.py`
covers the render and the CUDA hand-off and stops at `submit()`. How the ghost
*looks* is unverified too, and so is the grip-to-gripper calibration, by
construction — `tests/test_ghost.py` pins the *machinery* and leaves the shipped
constants free to be tuned.

Controllers on a shared session have no precedent elsewhere in this repository:
`xrAttachSessionActionSets` is legal once per `XrSession`, Teleop sidesteps it
with `XR_NVX1_action_context`, and the one existing shared-session example
(`examples/oglo_tactile`) exercises only Hand and Head trackers, which use no
actions. Treat that as the likeliest first-run blocker.
