<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MuJoCo XR

A MuJoCo scene rendered stereoscopically into an Isaac Teleop Televiz XR
session, with the operator's controllers drawn as markers.

## Status — read this before the diagram

| | |
|---|---|
| **Covered by tests** | [`ctest -L mujoco_xr`](#tests) — the frame conventions, the projection convention, the clock, the scene catalogue, the IK solver, the clutch and the ghost overlay. All of it is **pure CPU**: no GPU, no headset, no runtime, no window system. |
| **Never executed anywhere** | **The app itself.** There is one display mode, `kXr`, and it needs a headset plus a CloudXR runtime — so the frame loop, the renderer, OpenXR session sharing via `oxr_handles`, controllers on a shared session, the Vulkan→CUDA→`ProjectionLayer.submit()` path, and whether the runtime accepts the depth layer are **none of them run by any test or any developer here**. |
| **Wrong by construction until calibrated** | The workspace translation — see [Frames](#frames-cppframeshpp). |

Details in [Not verified anywhere in CI or on a developer desktop](#not-verified-anywhere-in-ci-or-on-a-developer-desktop).

**This used to claim more, and the claim was hollow.** A `--mode` flag offered
`window` and `offscreen` alongside `xr`. `window` never worked on any machine
anyone checked. `offscreen` rendered into memory, displayed nothing, could not
terminate on its own (`OffscreenBackend` never overrides `should_close()`), and
was invoked by no CI job, no rig and no script — only by a human copy-pasting
from this file. A GPU-backed `kOffscreen` test covered the Vulkan→CUDA→submit
path, and it too ran only when somebody on a GPU workstation typed `ctest`;
nothing in `.github/workflows/` installs `mujoco`, so **no `mujoco_xr` test has
ever run in CI**. Both are gone. Examples have no test infrastructure yet
([NVIDIA/IsaacTeleop#880](https://github.com/NVIDIA/IsaacTeleop/issues/880)); when
they do, a headless path should come back **with the job that runs it**, not
before.

Single process, single thread, **one** OpenXR session:

```
VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
     │                                        │
     │ vk_device / vk_physical_device         │ controller grip poses
     ▼                                        ▼
_mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer.submit()
```

The five names, since none of them are standard:

| name | what it is |
|---|---|
| `VizSession` | Isaac Teleop's rendering/display session (`isaacteleop.viz`). It owns the OpenXR instance and session, the Vulkan device, and the compositor layers. |
| `TeleopSession` | Isaac Teleop's *input* session (`isaacteleop.teleop_session_manager`) — trackers and the retargeting pipeline. Here it is handed the OpenXR handles `VizSession` already created, rather than making its own. |
| `get_oxr_handles()` | The accessor that makes the sharing possible: it hands out `VizSession`'s live `XrInstance`/`XrSession` so both halves run on **one** session. |
| `_mujoco_xr.Renderer` | This example's own pybind11 module (`cpp/`) — draws the MuJoCo scene with Vulkan into images it owns. |
| `ProjectionLayer.submit()` | The `VizSession` layer that takes those images (by CUDA pointer, no copy through host memory) and gives them to the compositor. |

## Scope

Renderer + MuJoCo + rig + **full teleop**: the right controller drives the arm
through a squeeze-clutched damped-least-squares IK loop, the trigger drives the
jaw, and A resets to the scene's `home` keyframe. Three scenes — `tabletop`
(no robot), `franka` and `so101` — and on the SO-101 a 50 %-transparent
**leader-gripper ghost** locked to the controller.

The control stack lives in Python (`robot_spec.py`, `ik_dls.py`, `teleop.py`)
because `cpp/scene_renderer.hpp` already draws the line there: C++ owns
`mjvScene` / `mjvOption` / `mjvCamera`, Python owns `mjModel` / `mjData` /
`mj_step`, and control writes `d.ctrl`. The practical consequence is that
**the whole of it is testable with no GPU, no headset and no runtime** — see
[Tests](#tests).

Controller markers are still drawn, for both hands, and that is deliberate: a
frame-convention bug and a control bug produce the identical symptom ("the arm
jumped"), and the markers are what separate them. The target-pose box (green
engaged, grey idle) is the only visual indication of clutch state, and the gap
between it and the tool is the IK's tracking error made visible.

## Build

**This example is its own wheel, and the wheel is the only way to run it.**

```bash
uv pip install ./examples/mujoco_xr     # from the repository root
python -m isaacteleop_examples.mujoco_xr
```

That second line **needs a headset and a running CloudXR runtime** — there is no
mode that does not. See [Run](#run).

That is the whole run path. Nothing is installed into `install/examples/mujoco_xr/`
any more, and there is no `uv run --directory ...` invocation. `uv pip install`
compiles the extension itself, through scikit-build-core, and does not read the
CMake build tree at all.

**Why a separate wheel rather than part of `isaacteleop`.** `uv pip install .`
at the repository root does not deliver this example — the root
`pyproject.toml`'s `install.components = ["isaacteleop_wheel",
"isaacteleop_binaries"]` filters out everything else. Folding it in was rejected:
`_mujoco_xr` links `libmujoco`, so the `isaacteleop` wheel's *contents* would
depend on whether the build host happened to have `mujoco` installed, and a
MuJoCo-linked `.so` would ship to every user. A separate wheel declares
`mujoco` as a real dependency instead of a build-host accident. This is only
possible because the module links **no viz target** — just `Vulkan::Vulkan`,
`CUDA::cudart_static` and `libmujoco`.

**Why the name is `isaacteleop-examples-mujoco-xr` and the import is
`isaacteleop_examples.mujoco_xr`.** This is a new pattern here — every other
example except `examples/haptic_feedback/` names its project bare
(`camera-viz`, `teleop-examples`), and this one was `mujoco-xr-example` for the
same reason. Bare is harmless for a project that is never installed. This one
**is** installed, and a bare top-level `mujoco_xr` in `site-packages` is an
example package claiming a plain, plausible, permanent name — right next to the
real `mujoco`. `isaacteleop_examples` is a **PEP 420 namespace**: it has no
`__init__.py` and no owning distribution, so the next example that wants to ship
a wheel can add `isaacteleop_examples.<other>` beside this one without either
wheel owning the directory. Adding an `__init__.py` there would turn it into a
regular package owned by this wheel and permanently close it — `pyproject.toml`'s
`wheel.packages` comment says so at the point where it could go wrong.

**The `isaacteleop` wheel must be installed first, into the same environment.**
It is a declared dependency but is not on any public index, so install it from
your local build before installing this example:

```bash
uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/
uv pip install ./examples/mujoco_xr
```

Both must land in **one** environment; that same environment is what
[`rigs/mujoco_xr.yaml`](../../rigs/mujoco_xr.yaml) runs from.

**`pip install -e` is not supported here — use a plain install.** An editable
install redirects `isaacteleop_examples.mujoco_xr` back to
`python/isaacteleop_examples/mujoco_xr/` in the source tree,
which is exactly where the in-tree CMake build drops *its* `_mujoco_xr*.so`; you
would silently import the root build's extension instead of the one the editable
install compiled. The redirect is what makes it silent: the wrong `.so` imports
fine right up until `mjModel*` crosses the boundary — a different interpreter,
potentially a different ABI, potentially a different `libmujoco`. Adding a
`[tool.scikit-build.editable]` block does not help; `mode = "redirect"` is the
default and the redirect *is* the problem. To iterate, re-run `uv pip install
--reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr` — it stays
incremental (~8 s) because the build directory persists.

### Prerequisites

| | |
|---|---|
| **`uv`** | Load-bearing. Install: <https://docs.astral.sh/uv/getting-started/installation/> |
| **CMake ≥ 3.21** | Not 3.20: the project floor is `3.20...3.25` (root `CMakeLists.txt`), but every command on this page goes through `--preset`, and `CMakePresets.json` declares `cmakeMinimumRequired 3.21.0`. Measured on this host with 3.28.3. |
| **A C++ compiler, the Vulkan SDK/loader, CUDA** | The same toolchain the rest of this repository needs; see `docs/source/getting_started/build_from_source/`. |
| **`glslangValidator`** (`apt install glslang-tools`) | The scene shaders are compiled to SPIR-V at build time. In the root build this was implied by `BUILD_VIZ`, which auto-disables when it is missing; on the wheel path it is a hard `FATAL_ERROR` from `cpp/CMakeLists.txt`, so an otherwise-fine host fails the install. |
| **A GPU with Vulkan + CUDA** | Needed to *run* the app at all; it fails at `VizSession.create` without one. Not needed to build it, and not needed by any test. |
| **A headset + CloudXR runtime** | Needed to run the app, full stop — `kXr` is the only display mode. Everything else on this page (build, tests) runs without one. |

**Build isolation does not save you from the toolchain rows above.**
`pyproject.toml`'s `build-system.requires` can declare a *Python* build
dependency — that is how `mujoco` gets into an isolated PEP-517 build — but
there is no way to declare CUDA, the Vulkan loader, or `glslangValidator` there.
On a host missing any of them, `uv pip install ./examples/mujoco_xr` fails
*inside* the isolated build, where the CMake error is wrapped in build-backend
output rather than reported as a missing dependency.

### The in-tree CMake build, which is a separate thing

The example is **also** wired into the root build, and that path still exists —
it is what the [tests](#tests) run against. It builds `_mujoco_xr*.so` in place
beside `python/isaacteleop_examples/mujoco_xr/__init__.py` and installs nothing.

**So the extension gets compiled twice, and that is a consequence of the design
rather than a bug**: once by the root CMake build for `ctest` (in place, by the
preset's `teleop_build_venv` interpreter), and once by scikit-build-core for the
wheel (by whichever interpreter is installing, whose ABI tag the wheel gets).
Collapsing them today would mean either shipping the root build's tree as a wheel
with no ABI tag, or dropping the in-tree ctest path. Keeping both is the
deliberate trade. The two never collide: `sdist.exclude` in `pyproject.toml`
keeps the in-place `.so` out of the wheel's package copy — see the comment there,
it is a sharper edge than it looks.

**What would collapse it:** the day `ctest` runs against the *installed wheel*
instead of the in-place `.so`. That removes the only reason the source tree needs
a compiled extension in it, and with it the whole `_mujoco_xr_standalone`
discriminator — `CMakeLists.txt` would have exactly one configuration. That is
blocked on packaging, not on this example: `isaacteleop` is a declared dependency
and is on no index, so the test environment cannot resolve it without a
`--find-links` pointing at a local build that may not exist yet.

You only need this path to run the tests. The order is not decorative, and steps
1 and 3 are the same command: on a fresh clone the interpreter in step 2 *does
not exist yet* — configure is what creates `teleop_build_venv`
(`cmake/SetupPython.cmake:152-200`) and then points `Python3_EXECUTABLE` at it —
and the mujoco probe runs **at configure time**, so it has to run again after
the wheel exists.

```bash
# 1. Configure once to create the build venv. This first pass necessarily
#    reports `-- mujoco_xr: skipped ...` — that is expected, not a failure.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 2. Install the wheel into the interpreter that configure just created.
#    `python -m pip` does not work: that venv has no pip.
uv pip install --python build/cmake-cpython-312/teleop_build_venv/bin/python "mujoco==3.11.0"

# 3. Re-configure. NOW the probe finds mujoco and the example is added.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 4. Build. There is no `cmake --install` step for this example any more.
cmake --build --preset py3.12 --parallel
```

`py3.12` is the preset name; its binary directory is `build/cmake-cpython-312`,
which is why steps 2 and 4 spell it out.

The first build of a fresh clone builds **the whole of Isaac Teleop**, not just
this example, so expect it to take a while — it has not been timed here, so no
number is quoted. What *was* measured on this host is the incremental case that
matters when you are iterating: **7.6 s** to rebuild after touching
`cpp/frames.hpp`.

This path is gated on `BUILD_VIZ`. There is no `BUILD_EXAMPLE_MUJOCO_XR` flag —
the only gate is whether the `mujoco` **wheel is installed in the interpreter
CMake resolves** (`Python3_EXECUTABLE`), because the C++ module compiles against
that wheel's headers and links its `libmujoco`.

`examples/mujoco_xr/CMakeLists.txt` is configured **two ways** and branches on
which: `add_subdirectory`'d from the root (the above), or as the top-level
project under scikit-build-core (the wheel). Standalone it sets up for itself the
three things root scope used to provide — `Python3_EXECUTABLE`, pybind11, and
where the `.so` goes. (`glslangValidator` is not among them: `cpp/CMakeLists.txt`
probes for it itself in both configures.) One difference is worth
knowing: a missing `mujoco` is a **skip** in the root build (nobody who did not
ask for this example should have their configure fail) and a **hard error**
standalone (a `return()` there would hand you a wheel with no extension in it).

### Confirming the in-tree example was actually built

A green build does **not** mean this example compiled. Step 3 prints one of:

```
-- mujoco_xr: ON (mujoco=3.11.0 lib=/.../site-packages/mujoco/libmujoco.so.3.11.0)
```

```
-- mujoco_xr: skipped -- '<python>' cannot import mujoco. Install it and re-run
   cmake --preset with: uv pip install --python <python> "mujoco==3.11.0"
```

Configure output is usually piped away, so the reliable check is:

```bash
cmake --preset py3.12 -DBUILD_VIZ=ON 2>&1 | grep '^-- mujoco_xr:'
```

The `ON` line also names the exact `libmujoco.so.*` that was linked, which is
the diagnostic for the failure mode below.

### The MuJoCo version is pinned in two files, and cross-checked against the build interpreter

| file | pin | decides |
|---|---|---|
| `pyproject.toml` | `build-system.requires` | what an isolated wheel build compiles and links against |
| `pyproject.toml` | `project.dependencies` | what the app imports at run time |
| `tests/pyproject.toml` | `dev` extra | what `ctest` resolves |

Becoming a wheel added a *third pin*, but not a third pin **file**: the new
top-level `pyproject.toml` replaced the deleted `python/pyproject.toml` rather
than joining it. The build-time pin is not optional — without `mujoco` in
`build-system.requires`, a PEP-517 isolated build would find none and emit a
wheel with no extension in it.

`CMakeLists.txt` deliberately hardcodes **no** version. It *reads* both files and
fails the configure if any pin disagrees with the version actually installed in
the build interpreter:

```
CMake Error: mujoco_xr: pyproject.toml pins mujoco==3.11.0, but
'<python>' has 3.12.0. ...
```

It matches **every** occurrence in each file (`REGEX MATCHALL`, not `MATCH`), so
the two pins inside `pyproject.toml` are checked against each other as well as
against the interpreter. One consequence: never restate the version number in
prose in those files — a `mujoco==` in a *comment* would be matched too, and a
harmless comment edit would become a configure failure. Write "the pin below".

Note the limit of the check: it compares against **the build interpreter only**.
It cannot see what `uv` will later resolve on the machine that runs the app, so
it is a drift detector, not a guarantee.

The reason any of this matters is that `mjModel*` and `mjData*` pointers cross
the pybind boundary: **exactly one `libmujoco` may be loaded in the process.**
`python/isaacteleop_examples/mujoco_xr/__init__.py` imports `mujoco` *before* the extension so that
the wheel's already-loaded library satisfies the extension's `NEEDED` entry, and
the extension is deliberately built with **no RPATH** so a mismatch is a clean
`ImportError` rather than a second copy loaded silently. `__init__.py` also
asserts `mj_versionString()` equality on both sides. Do not add an RPATH to "fix"
an import error — fix the version.

## Run

Every command in this section runs from the environment the two wheels were
installed into (see [Build](#build)). `--help` lists every flag, including the
ones `CloudXRLauncher` adds:

```bash
python -m isaacteleop_examples.mujoco_xr --help
```

**There is no `--mode`.** The app always opens a `kXr` session, so every command
below needs a headset and a CloudXR runtime; there is no desktop window and no
headless path. `--scene` takes a
catalogue id — `tabletop` (the default), `franka` or `so101`; the two robot
scenes need [a fetch](#scene-assets) first. `--scene-xml` overrides the
scene XML with a path. The default is **package data inside the installed
package** —
`<site-packages>/isaacteleop_examples/mujoco_xr/assets/tabletop.xml`. It lives at
`python/isaacteleop_examples/mujoco_xr/assets/tabletop.xml` in the source tree,
which is one directory deeper than you might expect precisely so that the same
one-`.parent` lookup in `app.py` resolves both in the wheel and in the source
tree that the tests import. Namespacing the package moved both paths in lockstep,
so the lookup is still one `.parent`.

### With a headset

Through the rig, which starts the CloudXR runtime alongside the app. Run it
from the repository root:

```bash
python -m isaacteleop.rig rigs/mujoco_xr.yaml
```

That `python` is the repo-wide convention (`docs/source/references/rig.rst`),
and it means **the environment you installed both wheels into** — not the build
venv (which has no `isaacteleop`) and not the system interpreter. The rig's
command is `{python} -m isaacteleop_examples.mujoco_xr --no-launch-cloudxr-runtime`,
and `{python}` expands to the interpreter you launch the rig with, so
`isaacteleop_examples.mujoco_xr` has to be installed *there*. If you have not
made such an environment:

```bash
uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/ --reinstall
uv pip install ./examples/mujoco_xr
```

Since this README warns that picking up the wrong venv is silent, here is how
to check before you start rather than after:

```bash
python -c "import sys, isaacteleop; from isaacteleop_examples import mujoco_xr; print(sys.executable); print(isaacteleop.__file__); print(mujoco_xr.__file__)"
```

Both packages must come from the same `site-packages`. The app's own startup log
prints the `isaacteleop:` line for the same reason.

Directly, against a runtime you started yourself:

```bash
# In one terminal — the runtime is a host singleton on WSS port 48322.
python -m isaacteleop.cloudxr --accept-eula

# In another.
python -m isaacteleop_examples.mujoco_xr --no-launch-cloudxr-runtime
```

`--no-launch-cloudxr-runtime` is not cosmetic: **omitting it makes the app start
its own CloudXR runtime**, which is the right thing when nothing else has, and
fatal when something has (the second runtime takes the port and kills the first).

**If no runtime is running and you pass `--no-launch-cloudxr-runtime` anyway**,
the failure comes out of `VizSession.create(kXr)` as an OpenXR instance/runtime
error before any of this example's own code runs — you will not see the startup
log block at all. Getting *no* `[mujoco_xr]` lines is the tell that it failed
here rather than anywhere downstream. (Not reproduced on this host: nobody has
run the app — see the [Status](#status--read-this-before-the-diagram) table.)

### Without a headset

You cannot run the app. There is no desktop window, no headless render, and no
flag that produces either — see the note under
[Status](#status--read-this-before-the-diagram) for why the two that used to
exist were removed.

**The only verification path on a machine with no headset is
[`ctest -L mujoco_xr`](#tests)**, and it exercises no GPU code at all. That is a
real gap, not a tidied-up one: everything below `_loop` — the renderer, the
Vulkan→CUDA export, `ProjectionLayer.submit()` — is now covered by nothing.

## A real startup log

**Transcribed from `_log_startup`, not captured from a run** — and that
distinction is the point. This block used to be a verbatim `--mode offscreen`
paste; with that mode gone the app only starts on a headset, and nobody here has
one, so **no one has ever seen these lines print**. Treat the shape as accurate
and the values as unconfirmed. Every assumption that is otherwise invisible is
printed exactly once, before the first frame:

```
[mujoco_xr] scene:      <site-packages>/isaacteleop_examples/mujoco_xr/assets/tabletop.xml
[mujoco_xr] isaacteleop: <site-packages>/isaacteleop/viz (version 1.5+local)
[mujoco_xr] mujoco:     3.11.0 (extension links 3.11.0)
[mujoco_xr] views:      2 (stereo)   view resolution: 1024x1024
[mujoco_xr] clip:       near=0.0500 far=50.00 (one pair -> VizSessionConfig, projection, submitted depth)
[mujoco_xr] reference space: LOCAL_FLOOR -- origin on the floor below the operator's start pose, so the z below is a measured floor datum. viz logs what the runtime actually offered on its own line.
[mujoco_xr] frames:     mj_from_xr translation = (-1.000, 0.000, -0.730) m. x is operator standoff; z is the FLOOR datum, valid because the reference space above is floor-origin. Neither term may be zeroed.
[mujoco_xr] clock:      FrameInfo.predicted_display_time; frames with no prediction are skipped, not sampled as 0
[mujoco_xr] depth submission: requested (ProjectionLayer depth_format=D32F). Whether the runtime ACCEPTED it is not queryable -- XrBackend::depth_layer_enabled_ is private with no accessor or binding. The absence of errors is NOT confirmation.
[mujoco_xr] controller markers: 2 validly tracked
[mujoco_xr] head tracking: origin sample at (0.000, 1.600, 0.000) m in the reference space. Walk or lean; the travel below must grow.
[mujoco_xr] projection convention verified on the first rendered frame (P[1][1] < 0, near->0, far->1)
```

The last three come from the first *rendered* frame rather than from startup, and
their order is fixed by `_loop`: markers are drawn before the scene-full check,
the head probe samples just before `render()`, and the projection is asserted
after it.

**Which of those must match on your machine, and which will not:**

| line | on your run |
|---|---|
| `scene:` / `isaacteleop:` | **Paths differ** — they are absolute and rooted in the `site-packages` you installed into. What matters is that both name the venv you expected, and **the same one**. This is the single most useful line on the block: if it points at a `site-packages` you did not expect, stop there. |
| `mujoco:` | **Both numbers must be identical** to each other (`3.11.0 (extension links 3.11.0)`). Two different versions means two `libmujoco`s in one process; `__init__.py` asserts this, so you would have seen an error instead. |
| `views:` | Always `2 (stereo)` — `kXr` is the only mode. The resolution is whatever the backend recommends and **varies by runtime/host**. |
| `clip:` / `frames:` | **Must match exactly** — they are compiled-in constants. If `frames:` reads anything but `(-1.000, 0.000, -0.730)` on an unmodified tree, something has been edited. |
| `reference space:` / `depth submission:` | Fixed text. Always identical. |
| `head tracking:` / `controller markers:` | **Vary with what the runtime is actually tracking.** `controller markers:` reprints whenever the count changes; `head tracking:` is followed either by a 6DoF confirmation or by the 3DoF warning — see `_HeadTravelProbe`. |
| `version 1.5+local` | **Varies** with the build. |

A scene with no arm in it (`tabletop`) additionally logs `teleop control is OFF:`
at WARNING, naming why. That is legitimate for `tabletop` and a real failure for
`franka` / `so101`, and the string is the only thing that tells the two apart.

## Conventions you can break

### Frames (`cpp/frames.hpp`)

`R_mj_from_xr = Rz(-90) * Rx(+90)`. XR `-Z` → MuJoCo `+x`, XR `+Y` → MuJoCo
`+z`, XR `+X` → MuJoCo `-y`. Testable definition: a point 1 m in front of the
operator at eye height `h` lands at MuJoCo `(+1, 0, h)` before the workspace
translation. `tests/test_frames.py` checks exactly that.

This is a **convention** and cannot be wrong at runtime. Note it deliberately
differs from `examples/retargeting/python/visualize_poses_mujoco_example.py`,
which applies `Rx(+90)` only (XR-forward → MuJoCo `+y`, not REP-103).

**`kTransMjFromXr` (`cpp/frames.hpp:44`) is the lever, and it is a calibration
that is routinely wrong.** It is `(-1.0, 0.0, -0.73)`, two independent terms:
`x` is operator standoff (the robot base sits ~1 m in front of the operator),
`z` is a floor datum that assumes the reference-space origin is on the floor.
Since the space is `LOCAL`, that assumption currently encodes "where the
operator's headset was at session start". Neither term may be zeroed.

There is **no recentre keypress and no runtime override** — changing the datum
means editing that constant and rebuilding. The recentring procedure is
therefore: stand where you intend to work, start the app, read the `frames:`
line in the startup log, compare the virtual table against the real one, and
adjust `z` by the observed error.

The rebuild that costs is **~8 seconds**, not a from-scratch build — measured on
this host, and worth knowing before you decide the loop is too slow to iterate
in:

```bash
# edit cpp/frames.hpp, then reinstall; this recompiles the extension.
uv pip install --reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr   # 8.2 s
```

`--reinstall-package` rather than a bare reinstall: the project version is fixed
at `0.0.0`, so without it `uv` sees the same version already installed and skips
the rebuild. It stays incremental because `pyproject.toml` sets
`build-dir = "build/wheel-{cache_tag}"` — the CMake cache persists between
installs instead of landing in a temp directory.

If you are iterating on the tests instead, `cmake --build --preset py3.12
--parallel` (7.6 s touching `frames.hpp`) rebuilds the in-place `.so` that
`ctest` uses; the two builds are independent and neither refreshes the other.

There is deliberately no `--workspace-offset` flag; see
[Deliberately not a flag](#deliberately-not-a-flag) below. Filed as a follow-up: a
`VizSession::Config::reference_space` option with a LOCAL_FLOOR → STAGE → LOCAL
ladder would remove the guesswork entirely.

#### Deliberately not a flag

A `--workspace-offset x y z` was considered and rejected. It cannot be a
pass-through argument: `Renderer` bakes `xr_from_mj_` **at construction** from
the compile-time constant (`cpp/scene_renderer.cpp:197`), while markers convert
per call through `mj_from_xr_pos`. A Python-side offset would therefore move the
markers and leave the scene where it was — and a marker displaced from the
operator's hand is exactly the symptom this example exists to make
*un*ambiguous. Doing it correctly means threading a runtime translation through
`frames.hpp`, `scene_renderer.cpp`, the bindings and `app.py`, turning one
compile-time source of truth into a value held in two places that can disagree.
That is a real feature, not a flag, and it is worth doing only once somebody has
actually run the calibration loop above — which requires a headset, and has
never been done (see the [Status](#status--read-this-before-the-diagram) table).

### Scene assets

`--scene` takes a **catalogue id**, not a path: `tabletop` (the default),
`franka` or `so101`. The catalogue is `robot_spec.SCENES`, one row per scene.
`--scene-xml <path>` is the escape hatch for a scene the catalogue does not
list. There is deliberately **no `--robot` flag** — the robot is always probed
from the loaded model, so a caller cannot assert a robot the model is not.

`franka` and `so101` wrap **unmodified** MuJoCo Menagerie models, which are
**fetched, not vendored**:

```bash
examples/mujoco_xr/scripts/fetch-menagerie.sh      # from the repository root
uv pip install ./examples/mujoco_xr --reinstall-package isaacteleop-examples-mujoco-xr
```

Three things about that pair of commands are not obvious and each has bitten
someone:

* **Fetch, then install — in that order.** The fetch unpacks Menagerie *into*
  `python/isaacteleop_examples/mujoco_xr/assets/<id>/`, which is package data,
  so the files only reach `site-packages` on the next install. Skip the
  reinstall and `--scene so101` works from the source tree and fails from the
  wheel. The fetch script prints the reinstall command when it finishes.
* **Nothing fetches at build time.** An isolated PEP-517 wheel build must not
  clone from GitHub, so this is an explicit step and the app fails at startup
  naming the script (`robot_spec.scene_missing`) rather than reaching for the
  network.
* **The wrapper has to be a sibling of the robot XML.** MuJoCo resolves an
  *included* file's `meshdir` against the included file's own directory and
  drops it when the wrapper lives elsewhere (measured on mujoco 3.11.0: a
  cross-directory `<include>` looks for `<include dir>/<mesh>.stl` and fails).
  That is why `assets/franka/ar_scene.xml` says `<include file="panda.xml"/>`
  with no path, and why the fetched payload and the one tracked file share a
  directory. The repository-root `.gitignore` keeps the payload untracked; that
  rule must **not** move into `examples/mujoco_xr/.gitignore`, because
  scikit-build-core reads `.gitignore` relative to the *project* root and would
  then also strip the robots out of the wheel.

A fetched wheel is ~55 MB rather than ~100 kB. That is the price of `--scene
so101` working from a bare `uv pip install` in a fresh environment.

The **leader-gripper ghost** (`so101` only) is the exception to "fetch, don't
vendor": three STLs, 1.3 MB, Apache-2.0, from `TheRobotStudio/SO-ARM100`, sitting
tracked in `assets/leader/` beside the `LICENSE`. Small enough to vendor, and it
keeps the ghost testable without a second fetch step. `assets/leader/leader_gripper.xml`
carries the full derivation of all three mesh transforms and the two rendering
risks that are documented rather than fixed.

The renderer draws `mjGEOM_BOX` and `mjGEOM_MESH` only, and skips
`mjGEOM_PLANE` outright (this is an AR scene; passthrough is the background). A
sphere or a capsule in the XML renders as nothing. The table **top** must sit
at `z = 0` or the `-0.73` floor datum is invalid for that scene. Lighting
declared in the XML is inert — `cpp/shaders/scene.frag` has one hardcoded
directional light and `mjvGLCamera` is bypassed.

### Culling

`cullMode` is `VK_CULL_MODE_NONE` during bring-up, and that is a decision, not
an omission. The projection flips Y (`P[1][1] < 0`), which inverts the
effective winding; get that wrong with culling on and the scene renders **black**,
which is routinely misdiagnosed as a depth or submit bug. Turn it on only after
a headset has confirmed the scene is visible.

## Tests

```bash
ctest --test-dir build/cmake-cpython-312 -L mujoco_xr --output-on-failure
```

| file | needs | covers |
|---|---|---|
| `test_frames.py` | nothing | the XR→MuJoCo axis map and quaternion order |
| `test_projection.py` | nothing | the clip-space convention (Y flip, standard Z, degenerate-fov rejection) |
| `test_app_helpers.py` | nothing | the NaN-safe `dt` clamp, the zeroed-`predicted_display_time` guard, the stalled-clock watchdog (including that it stays **silent** through a normal startup burst), the head-travel probe, and that the per-frame projection assertion actually fires |
| `test_scenes.py` | nothing, or a fetch | the scene catalogue: that the fetch script and `robot_spec.SCENES` name the same Menagerie directories, that the default needs no fetch, that every scene puts its table top at `z = 0`, that no scene emits a geom type the renderer silently drops, and that every robot scene has a `home` keyframe whose `ctrl=` agrees with its own `qpos` |
| `test_ik_dls.py` | nothing, or a fetch | resolution and the solver: `actuator_ctrlrange ∩ jnt_range` (on a synthetic arm built to make every kind of mismatch visible, **and** on the SO-101, where clamping to `ctrlrange` alone parks `wrist_roll` at 100 % of rated torque against a live joint limit), the Jacobian at the TCP rather than the body origin, the gravity feed-forward and its `kp > 0` guard, and that each resolution failure names what failed |
| `test_teleop.py` | nothing, or a fetch | the clutch: a constant reference-space offset and a right-multiplied orientation offset leave the `ctrl` trace unchanged, a left-multiplied one **changes** it (the negative control — do not delete it), zero-jump engage, hysteresis, auto-disengage holding the target, jaw polarity at both endpoints and with an inverted spec, rate limiting including a NaN `dt`, and that a commanded pure translation stays pure on the SO-101 |
| `test_ghost.py` | nothing, or a fetch | the overlay: that `mjv_updateScene` emits in geom-id order with the ghost last (the fact that replaced a second Vulkan pipeline), that the three leader parts form one assembly with sub-mm gaps, that the ghost tracks the controller and diverges from the target by exactly the clutch scaling, and that it is written **after** an A-reset |

**Every one of these runs on a CPU**, with no GPU, no headset, no CloudXR
runtime and no window system. The `franka` / `so101` cases in `test_scenes.py`
skip with a reason naming `scripts/fetch-menagerie.sh`, so an unfetched checkout
is green rather than red — and the checks that need no assets (the script/table
cross-check, the error-string check) still run there.

Nothing here is gated on hardware, because a permanently-skipping test reports
green while covering nothing. That principle is why the GPU-backed
`test_offscreen_render.py` was deleted rather than kept: it needed a Vulkan +
CUDA device, so it skipped everywhere except a workstation, and since nothing in
`.github/workflows/` installs `mujoco`, **not one test in this table has ever run
in CI either**. Wiring examples into CI is
[NVIDIA/IsaacTeleop#880](https://github.com/NVIDIA/IsaacTeleop/issues/880); until
that lands, `ctest -L mujoco_xr` means "a developer ran this locally".

## Not verified anywhere in CI or on a developer desktop

**Everything the GPU touches.** The renderer, the Vulkan→CUDA export,
`ProjectionLayer.submit()`, the frame loop that sequences them, OpenXR session
sharing via `oxr_handles`, whether the runtime accepts the depth layer, and
**controllers on a shared session** — none of it is executed by any test or on
any machine here. `kXr` is the only display mode, so the app does not start
without a headset plus a CloudXR runtime, and the `kOffscreen` test that once
covered the interop was removed for reporting green by skipping everywhere it
mattered. That is a deliberate, documented gap; the fix is CI
([#880](https://github.com/NVIDIA/IsaacTeleop/issues/880)), not a mode nobody
runs.

Nor is any of it anything about how the teleop *feels*: the tuned constants in
`robot_spec.py` come from an upstream implementation and are reproduced here in
simulation only, the ghost's placement relative to the operator's hand has never
been seen, and the two rendering risks in `assets/leader/leader_gripper.xml` (the
ghost writing depth into the reprojection buffer, and ghost self-overlap with
culling off) are both headset-only symptoms. Controllers on a shared session
have no precedent elsewhere in this repository: `xrAttachSessionActionSets` is
legal once per `XrSession`, Teleop sidesteps it with `XR_NVX1_action_context`,
and the one existing shared-session example (`examples/oglo_tactile`) exercises
only Hand and Head trackers, which use no actions. Treat that as the likeliest
first-run blocker.
