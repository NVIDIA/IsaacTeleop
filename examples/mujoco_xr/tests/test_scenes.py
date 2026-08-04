# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The scene catalogue: that every row loads, and that its invariants hold.

NOTHING HERE NEEDS A GPU, A HEADSET OR A RUNTIME. What the robot scenes DO need
is ``scripts/fetch-menagerie.sh`` to have been run, and every test that touches
one SKIPS WITH A REASON NAMING THAT SCRIPT when it has not. A hard failure there
would fail on every fresh clone, which is the fastest way to teach people to
ignore this file.
"""

import re
from pathlib import Path

import pytest

# Same importorskip shape as test_app_helpers.py:10 -- robot_spec has no heavy
# imports of its own, but it lives in the package whose extension may be absent.
robot_spec = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.robot_spec",
    reason="isaacteleop_examples.mujoco_xr is not importable",
)

FETCH_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch-menagerie.sh"

# Every geom type cpp/scene_renderer.cpp's render() switch actually draws.
# mjGEOM_PLANE is skipped on purpose (AR: passthrough is the background) and
# everything else falls through `default: continue` -- SILENTLY. A sphere or a
# capsule in a scene XML therefore renders as nothing at all, with no warning
# anywhere, which is why this is asserted rather than trusted.
DRAWN_GEOM_TYPES = ("mjGEOM_BOX", "mjGEOM_MESH")


def _mujoco():
    return pytest.importorskip("mujoco", reason="mujoco is not installed")


def _loadable(scene):
    """The scene's model, or a skip whose reason names the fetch script."""
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        pytest.skip(missing)
    mujoco = _mujoco()
    return mujoco.MjModel.from_xml_path(str(robot_spec.scene_path(scene)))


@pytest.fixture(params=robot_spec.SCENES, ids=lambda s: s.id)
def scene(request):
    return request.param


@pytest.fixture(
    params=[s for s in robot_spec.SCENES if s.menagerie_dir is not None],
    ids=lambda s: s.id,
)
def robot_scene(request):
    """Only the rows that carry an arm. Their invariants differ from tabletop's."""
    return request.param


# ---------------------------------------------------------------------------
# These two run everywhere, fetched or not. They are the reason an unfetched
# checkout still gains coverage from this file rather than a block of skips.
# ---------------------------------------------------------------------------


def test_the_fetch_script_and_the_catalogue_name_the_same_directories():
    """The one duplication in the fetch design, pinned.

    ``scripts/fetch-menagerie.sh`` is POSIX sh and cannot import robot_spec: on
    a fresh clone the wheel is not installed and there may be no interpreter
    with this package on its path at all. So it repeats the
    ``id:menagerie_dir:robot_xml`` mapping, and this test is what stops the two
    drifting. A drift is otherwise silent in the worst way -- the script fetches
    into a directory the app never looks at, reports success, and the app then
    says the assets are missing.
    """
    text = FETCH_SCRIPT.read_text()
    match = re.search(r'^SCENES="([^"]*)"', text, re.MULTILINE)
    assert match, f'no SCENES="..." line in {FETCH_SCRIPT}'
    from_script = {
        row.split(":")[0]: tuple(row.split(":")[1:]) for row in match.group(1).split()
    }
    from_table = {
        s.id: (s.menagerie_dir, s.menagerie_xml)
        for s in robot_spec.SCENES
        if s.menagerie_dir is not None
    }
    assert from_script == from_table


def test_the_default_scene_needs_no_fetch():
    """S7, asserted rather than assumed.

    The default must be loadable on an unfetched checkout, or every fresh clone
    fails at `python -m isaacteleop_examples.mujoco_xr`.
    """
    default = robot_spec.scene_by_id(robot_spec.DEFAULT_SCENE_ID)
    assert default.menagerie_dir is None
    assert robot_spec.scene_missing(default) is None


def test_an_unknown_scene_id_names_the_catalogue():
    with pytest.raises(KeyError) as excinfo:
        robot_spec.scene_by_id("panda")
    for known in robot_spec.scene_ids():
        assert known in str(excinfo.value)


def test_a_missing_scene_reports_the_fetch_script_by_path():
    """The skip/error string is a product surface: it is the only instruction.

    Built against a synthetic row rather than a real one so it runs identically
    on a fetched and an unfetched checkout.
    """
    ghost = robot_spec.Scene(
        id="nonesuch",
        label="not a real robot",
        xml="nonesuch/ar_scene.xml",
        menagerie_dir="vendor_nonesuch",
        menagerie_xml="nonesuch.xml",
    )
    missing = robot_spec.scene_missing(ghost)
    assert missing is not None
    assert robot_spec.FETCH_SCRIPT in missing
    assert "vendor_nonesuch" in missing
    # The reinstall half matters as much as the fetch half: fetching alone
    # leaves site-packages unchanged, and the symptom is identical.
    assert "reinstall" in missing


# ---------------------------------------------------------------------------
# Skip-gated on the fetch.
# ---------------------------------------------------------------------------


def test_every_catalogue_scene_loads(scene):
    model = _loadable(scene)
    assert model.ngeom > 0


def test_the_fetched_tree_is_at_the_pin_the_script_declares(robot_scene):
    """Catches a tree fetched before a pin bump.

    The script re-fetches when the stamp disagrees; this is what tells a human
    that it needs re-running, instead of the arm quietly being a different arm.
    """
    stamp = robot_spec.scene_path(robot_scene).parent / ".menagerie-pin"
    if not stamp.is_file():
        pytest.skip(robot_spec.scene_missing(robot_scene) or f"{stamp} is missing")
    declared = re.search(
        r"^PIN=\$\{MENAGERIE_PIN:-([0-9a-f]+)\}", FETCH_SCRIPT.read_text(), re.MULTILINE
    )
    assert declared, "no PIN= default in the fetch script"
    assert stamp.read_text().strip() == declared.group(1)


def test_every_scene_puts_the_table_top_at_z_zero(scene):
    """The one calibration every scene shares -- cpp/frames.hpp kTransMjFromXr[2].

    z = -0.73 says the MuJoCo z = 0 plane stands 0.73 m above the operator's
    physical floor. That is ONE number for ALL scenes, and what makes that legal
    is exactly this: every scene puts its table TOP at z = 0 with the robot base
    on it. A scene that thickens its table downward from z = 0 keeps this
    invariant; one that floats content above it does not, and invalidates the
    calibration for that scene alone -- silently, since nothing at runtime can
    tell.
    """
    mujoco = _mujoco()
    model = _loadable(scene)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    tops = []
    for i in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
        if "table" not in name:
            continue
        assert model.geom_type[i] == mujoco.mjtGeom.mjGEOM_BOX, (
            f"'{name}' is not a box; this check reads geom_size[2] as a half-height"
        )
        # geom_xpos, NOT geom_pos: the latter is relative to the geom's BODY,
        # and tabletop.xml hangs its top off a body at z = -0.02 -- so the
        # model-space reading is 0.02 and looks like a broken scene.
        assert data.geom_xmat[i][8] == pytest.approx(1.0), (
            f"'{name}' is rotated; its local z is not world z"
        )
        tops.append(data.geom_xpos[i][2] + model.geom_size[i][2])
    assert tops, f"scene '{scene.id}' has no geom with 'table' in its name"
    assert max(tops) == pytest.approx(0.0, abs=1e-9), (
        f"scene '{scene.id}' table top at z={max(tops)}, not 0"
    )


def test_every_scene_renders_only_geom_types_the_renderer_draws(scene):
    """A geom the renderer skips costs mjvScene budget and draws NOTHING.

    Runs the same mjv_updateScene the renderer runs (mjCAT_ALL, a default
    mjvOption), and checks every emitted geom against the switch in
    cpp/scene_renderer.cpp. Menagerie models carry collision geoms of types this
    renderer cannot draw -- spheres, capsules -- and they stay invisible here
    only because the default mjvOption's geomgroup admits groups 0-2 while
    so101.xml puts collision in groups 3 and 4. That is a property of the
    MODELS, not of this app, so a Menagerie bump can change it.
    """
    mujoco = _mujoco()
    model = _loadable(scene)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    option = mujoco.MjvOption()
    mujoco.mjv_defaultOption(option)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    scn = mujoco.MjvScene(model, 20000)
    mujoco.mjv_updateScene(
        model, data, option, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scn
    )
    assert scn.ngeom > 0
    seen = {mujoco.mjtGeom(int(scn.geoms[i].type)).name for i in range(scn.ngeom)}
    assert seen <= set(DRAWN_GEOM_TYPES), (
        f"scene '{scene.id}' emits {sorted(seen - set(DRAWN_GEOM_TYPES))}, which "
        "cpp/scene_renderer.cpp's render() switch drops without a word"
    )


def test_every_robot_scene_has_a_home_keyframe_carrying_ctrl(robot_scene):
    """``home`` is required, and a qpos-only ``home`` is worse than none.

    The control step refuses a model without a keyframe named ``home`` -- it is
    both the A-reset pose and the nullspace bias posture. But the A-reset calls
    mj_resetDataKeyframe, which writes ``ctrl`` from the keyframe too: a
    keyframe with no ``ctrl=`` resets every actuator command to ZERO, and a
    position-servo arm then drives to qpos 0 and collapses. Assert both halves,
    and assert they AGREE, or the very first A-press moves the arm.
    """
    mujoco = _mujoco()
    model = _loadable(robot_scene)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    assert key >= 0, f"scene '{robot_scene.id}' has no keyframe named 'home'"
    ctrl = model.key_ctrl[key]
    assert ctrl.shape[0] == model.nu
    assert ctrl.any(), f"scene '{robot_scene.id}': home keyframe has no ctrl="

    # ctrl must equal the actuated qpos, joint by joint, or A-reset commands a
    # pose the keyframe did not set.
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, key)
    for a in range(model.nu):
        if model.actuator_trntype[a] != mujoco.mjtTrn.mjTRN_JOINT:
            continue  # the Franka's jaw is a tendon, on a remapped 0..255 scale
        jid = model.actuator_trnid[a][0]
        assert data.ctrl[a] == pytest.approx(data.qpos[model.jnt_qposadr[jid]]), (
            f"scene '{robot_scene.id}': home ctrl[{a}] disagrees with its own qpos"
        )
