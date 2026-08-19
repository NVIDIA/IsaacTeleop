<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MuJoCo XR

A MuJoCo scene rendered stereoscopically into an Isaac Teleop Televiz XR
session, with an SO-101 leader gripper locked to the operator's right hand.

Single process, single thread, **one** OpenXR session:

```
VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
     │                                        │
     │ recommended resolution                 │ controller grip poses
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
| **Covered by tests** | [`ctest -L mujoco_xr`](#tests) — the frame conventions, the frustum, the clock, the ghost overlay and its jaw channel, all pure CPU; **plus `test_readback.py`, which drives the real GPU path** (mjr_render → blit → flip/invert → PBO → CUDA). That one needs CUDA-OpenGL interop, so it wants a discrete NVIDIA GPU; it skips loudly elsewhere. **Measured on Jetson/Tegra it skips**, because `cudaGLGetDevices` reports the EGL context on no CUDA device — so a green `ctest` there does *not* mean the GPU path ran. |
| **Never executed anywhere** | **The XR half** — everything downstream of the readback. See [Not verified anywhere](#not-verified-anywhere-in-ci-or-on-a-developer-desktop). |
| **Wrong by construction until calibrated** | The workspace translation, for any scene that adds static content — see [Frames](#frames-cppframeshpp). The shipped ghost-only scene does not show it. |

Nothing in `.github/workflows/` installs `mujoco`, so the example is never
configured and **not one of its tests has ever run in CI**. Green means one
developer ran it locally. Wiring examples into CI is
[NVIDIA/IsaacTeleop#880](https://github.com/NVIDIA/IsaacTeleop/issues/880).

## Scope

Renderer + MuJoCo + rig, and one scene: `assets/scene.xml` — an **SO-101
leader gripper ghost** locked to the right controller's grip pose, and nothing
else. No table, no blocks, no ground plane: this is an AR scene and passthrough
is the background.

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

Two calibrations, and they are different in kind. `cpp/frames.hpp` is a
*convention* fixed by two specs and cannot be wrong at runtime.
`_QUAT_GRIP_FROM_GHOST` / `_POS_GRIP_FROM_GHOST` in `app.py` are a *measurement*
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

A *second* calibration, and a different kind: `_EULER_GRIP_FROM_GHOST_DEG` and
`_POS_GRIP_FROM_GHOST` place the leader gripper on the operator's hand. Without
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
the hand, and `_POS_GRIP_FROM_GHOST` slides it along the grip axes if the angle
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

The ghost's four STLs are **fetched, not vendored** — 2.3 MB of binary in a
source tree is a poor trade when upstream publishes them at a stable commit, and
Git LFS made every clone pay for them. Run it once, then reinstall, because they
are package data:

```bash
examples/mujoco_xr/scripts/fetch-so-arm.sh          # from the repository root
uv pip install --reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr
```

Nothing fetches at build time: an isolated PEP-517 wheel build must not reach
the network, so the app fails at startup naming the script and `test_ghost.py`
**skips** with the same reason. Downloads are checksum-verified against a pinned
commit — a silently substituted mesh renders as a broken gripper rather than an
error, which has already cost a debugging session.

The script also pulls `so101_new_calib.urdf`, which is where the trigger's hinge
and its 0..100° travel come from, so it is on disk to check them against. Three of the four
meshes are leader-specific print parts; the fourth is the **STS3215 servo**,
shared with the follower. It is not decoration — `wrist_roll` is a C-shaped
bracket that wraps the servo, so without it the assembly has an open notch where
the motor belongs and reads as a broken asset.

It declares **two** mocap bodies — the gripper and its trigger — because the
trigger articulates; a jointed child of a mocap body would be a dynamic joint
that `mj_step` integrates gravity into, and a mocap body is kinematic by
construction.

The ghost is **opaque**, and `test_ghost.py` asserts it. That removes the
draw-order constraint (at alpha 1.0 the depth test decides everything) and the
ghost-writes-depth-into-the-reprojection-buffer concern. A scene that puts a
robot under the ghost and drops the alpha back takes both on again: `mjv_updateScene`
emits in geom-id order, so the `<include>` must come **last**. Nothing asserts
that ordering today — it only matters below alpha 1.0, so the test belongs with
the scene that needs it.

**Pass MuJoCo an absolute scene path.** Measured on mujoco 3.11.0, a *relative*
model path mis-composes the mesh paths of an `<include>`d file in a
subdirectory and fails with `Error opening file '<a path that exists>'`.
`DEFAULT_SCENE` in `app.py` is absolute for this reason.

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
