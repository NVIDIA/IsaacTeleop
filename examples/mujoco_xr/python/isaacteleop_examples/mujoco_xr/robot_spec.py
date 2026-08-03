# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The tables that make this app multi-robot, and the only place a scene is named.

Ported from ``MuJoCoXR/src/robot_spec.{h,c}``, which this module deliberately
mirrors by name so provenance is greppable.

WHAT IS HERE: ``ROBOTS`` -- one row per arm, holding model-file names plus the
tuned constants the teleop stack cannot derive -- and ``SCENES`` -- one row per
loadable scene, holding an id, a menu label and where its XML comes from.
THERE IS NO FOREIGN KEY BETWEEN THEM. A scene does not name its robot and a
robot does not list its scenes; the link is made at load time by probing the
model (``robot_probe``). That absence is deliberate and is what the rest of this
docstring argues for.

They are two tables on purpose, and the reason is the change most likely to come
next. A scene is not a robot: ``/code/Lab`` already ships a second SO-101 scene
(``Isaac-Stack-Cube-SO101-IK-Abs-v0``), so the next entry this catalogue grows is
more likely a second SO-101 scene than a third arm. Under one fused table that
would mean a duplicated robot row -- and because the robot is PROBED from the
model rather than named, a duplicated row makes ``tcp_body`` stop discriminating
and turns the "exactly one match" rule into a hard failure at load. One table
would make the likeliest next change brick the app; two tables make it one
``Scene`` row.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import mujoco

# PACKAGE DATA, resolved from inside the package -- see app.DEFAULT_SCENE for
# why this is plain ``__file__`` arithmetic and not ``importlib.resources``.
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# The fetch step, named in full because it is what every "assets are missing"
# error line has to print. Relative to the example root (the directory holding
# pyproject.toml), which is three parents up from ASSETS_DIR's parent.
FETCH_SCRIPT = "examples/mujoco_xr/scripts/fetch-menagerie.sh"


@dataclass(frozen=True)
class Scene:
    """One loadable scene.

    ``id`` IS THE ONLY NAME. It is simultaneously the ``--scene`` token, the
    directory under ``assets/`` that the scene XML lives in, and the directory
    ``scripts/fetch-menagerie.sh`` unpacks Menagerie into. That convention is
    what lets the fetch script and this table build the same path from one
    string instead of each carrying its own per-robot literals.

    The id crosses as a STRING rather than an index, deliberately: a wrong
    string fails at ``argparse`` with the catalogue printed, while a wrong index
    would silently load a different robot.
    """

    # ``--scene`` token, and the assets/ subdirectory.
    id: str
    # Shown to a human: the ``scene:`` startup log line and ``--help``. The one
    # UI string in this module.
    label: str
    # Path of the scene XML relative to ASSETS_DIR.
    xml: str
    # Menagerie directory this scene's robot is fetched from, or None for a
    # scene authored entirely in this repository.
    #
    # THESE ARE NOT OUR SCENE IDS and the two spellings must not be conflated:
    # `franka_emika_panda` stages as `franka`, `robotstudio_so101` as `so101`.
    # scripts/fetch-menagerie.sh repeats this mapping (it is POSIX sh and cannot
    # import this module on a fresh clone, where the wheel is not installed
    # yet); tests/test_scenes.py parses the script and asserts the two agree, so
    # the duplication cannot drift silently.
    menagerie_dir: str | None
    # The robot XML inside that Menagerie directory -- the file ar_scene.xml
    # ``<include>``s, and therefore the file whose presence means "fetched".
    menagerie_xml: str | None


# In menu order. The default is FIRST and stays `tabletop`: it is the only scene
# that needs no fetch, so an unfetched checkout keeps working unchanged.
SCENES: tuple[Scene, ...] = (
    Scene(
        id="tabletop",
        label="AR tabletop (blocks, no robot)",
        xml="tabletop.xml",
        menagerie_dir=None,
        menagerie_xml=None,
    ),
    Scene(
        id="franka",
        label="Franka Emika Panda",
        xml="franka/ar_scene.xml",
        menagerie_dir="franka_emika_panda",
        menagerie_xml="panda.xml",
    ),
    Scene(
        id="so101",
        label="SO-101",
        xml="so101/ar_scene.xml",
        menagerie_dir="robotstudio_so101",
        menagerie_xml="so101.xml",
    ),
)


# The scene loaded when --scene is not given. Named rather than taken as
# SCENES[0] so the menu can be reordered without moving the default.
DEFAULT_SCENE_ID = "tabletop"


def scene_ids() -> tuple[str, ...]:
    """Every ``--scene`` token, in menu order."""
    return tuple(s.id for s in SCENES)


def scene_by_id(scene_id: str) -> Scene:
    """The row for ``scene_id``.

    Raises ``KeyError`` for an unknown id rather than returning None: the app
    passes ``scene_ids()`` to argparse's ``choices=``, so a bad token is already
    rejected there with the catalogue printed, and every caller that reaches
    here has a valid id or a bug.
    """
    for scene in SCENES:
        if scene.id == scene_id:
            return scene
    raise KeyError(f"no scene '{scene_id}'; known scenes: {', '.join(scene_ids())}")


def scene_path(scene: Scene) -> Path:
    """Absolute path of the scene XML. May not exist -- see ``scene_missing``."""
    return ASSETS_DIR / scene.xml


def scene_missing(scene: Scene) -> str | None:
    """Why this scene cannot be loaded, or None if it can.

    Returns a STRING rather than raising so both callers can use it: the app
    turns it into a startup error, and the tests turn it into a skip reason.
    A test that failed here instead of skipping would fail on every checkout
    that has not run the fetch script, which is every fresh clone.

    Checks the Menagerie robot XML rather than the directory: ``scripts/
    fetch-menagerie.sh`` creates ``assets/<id>/`` for the tracked
    ``ar_scene.xml`` regardless, so an existing directory proves nothing.
    """
    path = scene_path(scene)
    if scene.menagerie_dir is None:
        return None if path.is_file() else f"{path} is missing"
    robot_xml = path.parent / str(scene.menagerie_xml)
    if robot_xml.is_file():
        return None
    return (
        f"scene '{scene.id}' needs MuJoCo Menagerie's {scene.menagerie_dir}/, "
        f"which is not in {path.parent}. It is FETCHED, not vendored -- run "
        f"`{FETCH_SCRIPT}` from the repository root, then reinstall the wheel "
        f"(`uv pip install ./examples/mujoco_xr --reinstall-package "
        f"isaacteleop-examples-mujoco-xr`) so the fetched files reach "
        f"site-packages."
    )


# ===========================================================================
# The robot table.
# ===========================================================================


@dataclass(frozen=True)
class Robot:
    """One arm, named entirely in model-file terms plus numbers nothing derives.

    Every field is either a name resolved through ``mj_name2id`` or a tuned
    constant. Nothing here is a resolved id, because this table is module-level
    and ids are per-model; resolution lands in ``ik_dls.IkDls``.
    """

    # THE DISCRIMINATOR. robot_probe() identifies the loaded model by looking up
    # this one body name, so it must be unique across the whole table (asserted
    # at import, below). It is also the frame the TCP is reported in: the TCP
    # pose is this body's pose offset by tcp_offset, so tcp_body chooses the tool
    # ORIENTATION as well as the position.
    #
    # THE TWO ROBOTS' TOOL FRAMES DO NOT AGREE, and that is fine only because of
    # the invariant stated at teleop.Teleop._engaged_goal. Measured at each
    # robot's home: the Franka's `hand` frame and the SO-101's `gripper` frame
    # are 135.85 deg apart, and the SO-101's own authored tool site
    # (`gripperframe`) is exactly 90.0000 deg about +y from the `gripper` body
    # frame used here. Nothing corrects for either, because nothing has to -- the
    # teleop orientation path is purely relative.
    tcp_body: str
    # Arm joints, base to tool. ORDER IS LOAD-BEARING: it is the column order of
    # the Jacobian and the row order of dq.
    #
    # A plain tuple, and `narm` is `len(joints)`. The reference implementation
    # carries a fixed-capacity array with a leading-run convention and a NULL
    # terminator; those are C artifacts and do not port.
    joints: tuple[str, ...]
    # Position-servo actuator for the jaw. A NAME, never "the one after the arm
    # joints": the Franka's is the 8th actuator and the SO-101's is the 6th, and
    # that is a coincidence of both models rather than a rule.
    gripper_act: str

    # TCP position in the tcp_body frame, in METRES: the grasp midpoint, so the
    # operator's clutch pivots about the point between the jaws rather than a
    # servo housing.
    #
    # WHERE THE NUMBER COMES FROM, because the two shipped rows got it by
    # different routes and the difference is the part to get right:
    #   - SO-101: copied verbatim from so101.xml's authored `gripperframe` site
    #     `pos`. That works only because the site is a direct child of the
    #     `gripper` body, so its `pos` already IS an offset in this frame. Its
    #     ORIENTATION is 90 deg off (see tcp_body) and is not read here.
    #   - Franka: no authored site sits at the grasp midpoint, so 0.103 m along
    #     the +z tool axis was taken off panda.xml's finger geometry.
    # So: use a tool site's `pos` if one hangs under tcp_body; transform it first
    # if the site hangs under a different body; measure the midpoint between the
    # jaw geoms if there is no site at all. Verify whichever route you took the
    # way the SO-101's was verified -- forward-kinematic the offset at the `home`
    # keyframe and compare against the site's world position (that check matched
    # to 4e-17 m, and tests/test_ik_dls.py re-runs it).
    tcp_offset: tuple[float, float, float]

    # Weight applied to the three ROTATION rows of the task error and Jacobian.
    # 1.0 means "1 rad of orientation error is worth 1 m of position error".
    #
    # MEASURED, NOT DERIVED, and the distinction is the useful part. Two
    # candidate derivations were built and both were killed by the same test:
    # tool length gives 0.098 for the SO-101, and sigma_min(J_pos)/sigma_max(J_rot)
    # gives 0.0495 -- a 1 % match to the measured 0.05 -- but that same expression
    # predicts 0.177 for the Panda, whose measured optimum is 1.0 and monotone. A
    # formula that is right on one arm and 5.6x wrong on the other is a fit.
    #
    # The statable rule, which extends to robot #3 better than a formula would:
    # on a FULL-RANK arm the optimum is 1.0, because the natural metric is
    # achievable and any weight is a distortion -- so a 6-dof arm needs no sweep
    # at all. On a RANK-DEFICIENT arm the optimum is wherever unachievable
    # orientation stops corrupting achievable position, and that boundary depends
    # on the distribution of commanded residuals, not on the Jacobian. It is a
    # property of the task, not of the kinematics. Start a sweep at the tool
    # length and walk down to the knee.
    w_rot: float

    # Damping in the DLS solve: A = J J' + lambda^2 I6. Named `dls_lambda`
    # because `lambda` is a Python keyword; it is the reference's `lambda`.
    #
    # Its units are those of a singular value of the weighted J -- metres of TCP
    # motion per radian of joint motion -- so it is comparable against the sigmas
    # quoted in the rows below, and that comparison is the whole tuning story: a
    # task direction is attenuated by lambda^2/sigma^2, so raising lambda makes
    # the arm calmer near a singularity and lazier everywhere else.
    #
    # Both shipped rows use 0.05, and 0.05 is where a third robot should start.
    # To check it, sweep 0.02 -> 0.10 and read the position median off a replay.
    # If the median is flat across that sweep the arm is not damping-limited in
    # motion and the default stands; only an observed jitter or stall at full
    # extension argues for moving it. That sweep was run on the SO-101 (3.2 ->
    # 3.3 mm, non-monotone) and is why its row keeps the Franka's value.
    dls_lambda: float

    # Gain on the nullspace bias toward the `home` KEYFRAME posture -- the same
    # keyframe ik_dls refuses the model without. 0 disables the term.
    #
    # MUST BE 0 UNLESS len(joints) > 6, and "6" is the trap: a nonsingular 6-dof
    # arm on a 6-D task has dim N(J) = 0, so there is no nullspace to bias and
    # the entire term lands on the task command as uncommanded tool motion. The
    # rule is `> 6`, NOT ">= 6" -- and the likeliest third robot in this
    # ecosystem is exactly the 6-dof case that reads as safe and is not. Counted,
    # not recalled: of the arms Menagerie ships, UR5e, UR10e and ufactory_lite6
    # are the 6-dof ones this rule catches, while kinova_gen3 (7) and
    # ufactory_xarm7 (7) are genuinely redundant and want a non-zero gain. Check
    # the width against the model rather than the marketing name -- the same
    # product line ships in both. Measured by forcing narm = 6 on the Franka:
    # ns_gain = 0.1 takes the position error 21.255 -> 31.958 mm and the spurious
    # rotation 0.507 -> 0.979 deg, buying nothing.
    #
    # ENFORCED AS A LOAD-TIME ERROR by _validate() below, at import, so a bad row
    # cannot reach a model.
    ns_gain: float

    # Control-display ratio for the clutch: the target moves clutch_scale metres
    # per metre of hand travel. An operator human-factors parameter, and on a
    # short arm a reach limiter.
    clutch_scale: float

    # Jaw endpoints in actuator-ctrl units, TABULATED rather than derived from
    # actuator_ctrlrange. Deriving would silently follow a Menagerie bump, and
    # ctrlrange supplies the scale but NOT THE POLARITY: both shipped robots are
    # "low = closed" only by coincidence, and Menagerie's Robotiq 2F-85 is 0..255
    # with 0 = OPEN, so a derived mapping inverts that gripper. `closed` may be
    # numerically ABOVE `open`; polarity lives in this table, not in the mapping.
    # teleop.Teleop warns (does not correct) at init if an endpoint has fallen
    # outside the model's ctrlrange.
    gripper_closed: float
    gripper_open: float

    @property
    def narm(self) -> int:
        return len(self.joints)


ROBOTS: tuple[Robot, ...] = (
    Robot(
        tcp_body="hand",
        joints=(
            "joint1",
            "joint2",
            "joint3",
            "joint4",
            "joint5",
            "joint6",
            "joint7",
        ),
        gripper_act="actuator8",
        # Grasp midpoint in the hand frame, 103 mm down the +z tool axis.
        tcp_offset=(0.0, 0.0, 0.103),
        # 1.0 because the Panda is full-rank for a 6D task: the natural metric is
        # achievable, so any weight is a distortion. Measured monotone -- the
        # fingertip error is worst at every value below 1.0.
        w_rot=1.0,
        dls_lambda=0.05,
        # 7 joints against a 6D task leaves a genuine 1-dimensional nullspace, so
        # this is a real projector here and the bias costs the task nothing.
        # Contrast the SO-101 row.
        ns_gain=0.1,
        clutch_scale=1.0,
        # panda.xml:275 says in its own comment that this is a per-model remap.
        # 0 = closed, 255 = open.
        gripper_closed=0.0,
        gripper_open=255.0,
    ),
    Robot(
        tcp_body="gripper",
        # Five. The SO-101 is one rotational DOF short of the 6D task, which is
        # the single fact that drives w_rot, ns_gain and clutch_scale below away
        # from the Franka's values.
        joints=(
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
        ),
        gripper_act="gripper",
        # so101.xml's own `gripperframe` site, verbatim: (0.012, -0.000218,
        # -0.098127) in the `gripper` body frame. Verified to land on the site's
        # world position at home, (0.2735, 0.0118, 0.0899). Note the tool axis is
        # -z here and +z on the Franka; see Robot.tcp_body.
        tcp_offset=(0.012, -0.000218, -0.098127),
        # 0.05: the measured knee, three independent sweeps agreeing, over a
        # 360-frame replay script.
        #
        #   w_rot | pos med / p90 / max (mm) | ori med / p90 / max (deg)
        #   1.00  |  55.8 /  91.6 / 95.1     |  1.0 /  1.4 /  3.7
        #   0.20  |  19.2 /  40.3 / 42.2     |  7.7 / 13.9 / 14.5
        #   0.10  |   6.9 /  14.0 / 14.7     | 10.7 / 20.0 / 20.9
        #   0.05  |   3.3 /   4.5 /  5.5     | 11.6 / 22.2 / 23.2
        #   0.02  |   2.1 /   3.9 /  5.6     | 11.9 / 23.0 / 24.0
        #   0.00  |   1.7 /   3.3 /  5.6     | 34.2 / 51.0 / 52.1
        #
        # 0.10 -> 0.05 buys half the position error for 0.9 deg of median
        # orientation; 0.05 -> 0 costs 22.6 deg to buy 1.6 mm. Both endpoints are
        # bad, which is why this is a tuned scalar and not a mode flag.
        #
        # A SECOND, DIFFERENT TRAJECTORY, recorded because the two numbers must
        # not be read as one refuting the other: over a sweep of RANDOM REACHABLE
        # targets -- a workspace the shipping script provably never enters (0/360
        # clamped frames, 0 contacts) -- w_rot = 0.05 has a ~155 mm max against
        # ~40 mm at 0.10. That tail is the workspace-edge fold: near the reach
        # limit the arm cannot satisfy position either, and a low w_rot stops
        # trading orientation away to try. Nothing in this file fixes it, the
        # domain-correct fix is a manipulability clamp on the TARGET, and if a
        # researcher reports it as an IK bug this is the paragraph to read them.
        # THIS IS THE ONE LITERAL TO RAISE if the first on-device session works
        # near full extension.
        w_rot=0.05,
        # Shared with the Franka deliberately. A settle-only argument for 0.03
        # was withdrawn after measurement: in motion lambda is flat (0.02 -> 0.10
        # moves the median 3.2 -> 3.3 mm, non-monotone), and at w_rot = 0.05 the
        # smallest singular value is 0.0207, so lambda^2/sigma^2 = 5.8 and the
        # damping is doing real work holding the near-singular direction
        # together.
        dls_lambda=0.05,
        # ZERO, and this is a CORRECTNESS choice rather than a tuning one.
        #
        # The SO-101's J is 6x5 with singular values 1.769 / 1.321 / 0.556 /
        # 0.0953 / 0.0807 -- full COLUMN rank, so dim N(J) = 0. THERE IS NO
        # NULLSPACE ON THIS ARM, and `ns_gain` is named for an operation that
        # does not exist here. What ik_dls actually computes is the DAMPED
        # projector I - J'(JJ' + lambda^2 I)^-1 J, which is not a projector and
        # leaks as lambda^2/sigma^2: 0.55 % at w_rot = 1.0 but 27.6 % at the 0.05
        # shipped above -- 119x more, because w_rot scales the rotation rows and
        # shrinks sigma with them.
        #
        # That leak lands on the task command. Measured at w_rot = 0.05, on a
        # pitch axis the arm hits EXACTLY: ns_gain = 0.1 produces 1.13 mm and
        # 5.43 deg of uncommanded motion, ns_gain = 0.3 produces 1.85 mm and
        # 9.13 deg, against 0.00 mm / 0.00 deg at zero. A commanded pure
        # translation must produce a pure translation -- that is the property a
        # teleoperator's hand-eye loop is closed around, and 7 deg of spurious
        # tool roll is the most disorienting thing you can hand them. It went
        # unnoticed for two rounds upstream because the metric everyone was
        # watching was a POSITION median, which cannot see a rotation.
        # tests/test_ik_dls.py's pure-translation test is what catches it now.
        ns_gain=0.0,
        # 0.5, the highest-value number measured on this arm. At 1.0 the
        # 360-frame script pins a joint against its stop on 69 frames (19 %) with
        # a 22.8 mm worst error; at 0.5, 0 frames and 14.0 mm. The Franka's
        # workspace swallows a 1:1 hand mapping and this arm's does not, so the
        # control-display ratio is where the reach difference is absorbed -- not
        # in the rate limits, which are shared (see teleop.py) and were measured
        # to make lag WORSE when tightened.
        clutch_scale=0.5,
        # /code/Lab's SO101_GRIPPER_CLOSE / _OPEN, the identical affine map.
        # 1.745 rad is inside so101.xml's ctrlrange of (-0.17453, 1.74533), which
        # teleop.py re-checks at init rather than assuming.
        #
        # gripper_closed = 0.0 DOES NOT CLOSE THE JAWS, and that is imported from
        # Lab along with the constant. Measured aperture (centroid of the three
        # fixed_jaw_sph_tip* geoms to the centroid of the three
        # moving_jaw_sph_tip*, at the home posture): 1.745 -> 129.9 mm, 0.0 ->
        # 16.3 mm, -0.17453 -> 4.4 mm. So a fully squeezed trigger stops 16 mm
        # apart: it cannot pinch anything thinner than that, it applies full
        # rated torque to anything thicker, and exactly zero at 16 mm. -0.17453
        # is INSIDE ctrlrange -- the travel is there and this map declines to use
        # it. Kept at Lab's value anyway, because Lab's 0.0 is right FOR LAB: a
        # binary open/close action on ~40 mm cubes, where the last 16 mm is
        # wasted stroke. A continuous teleop trigger is a different instrument
        # and 0.0 is probably wrong for it. TRIGGER: the first on-device session
        # that tries to pick up anything thin -> set this to -0.174533.
        gripper_closed=0.0,
        gripper_open=1.745,
    ),
)


def _validate(robots: tuple[Robot, ...]) -> None:
    """Table invariants, checked AT IMPORT.

    A load-time error, not a load-time check: every one of these makes a row
    silently drive an arm wrongly, and none of them needs a model to detect. That
    also means any test that merely imports this module covers them.
    """
    seen: dict[str, int] = {}
    for i, robot in enumerate(robots):
        if robot.tcp_body in seen:
            raise ValueError(
                f"ROBOTS[{i}] and ROBOTS[{seen[robot.tcp_body]}] share tcp_body "
                f"'{robot.tcp_body}'. It is the probe's only discriminator, so "
                "two rows carrying it make robot_probe() fail on every model "
                "either one describes."
            )
        seen[robot.tcp_body] = i

        # THE ONE THAT SHIPS A SILENTLY-WRONG ROBOT. `> 6`, not `>= 6`: a
        # nonsingular 6-dof arm on a 6-D task has dim N(J) = 0, so the bias term
        # has nowhere to live and lands entirely on the task command.
        if robot.ns_gain != 0.0 and robot.narm <= 6:
            raise ValueError(
                f"ROBOTS[{i}] ('{robot.tcp_body}') sets ns_gain={robot.ns_gain} "
                f"with {robot.narm} arm joints. A 6-D task leaves an "
                f"{robot.narm}-joint arm dim N(J) = 0, so there is no nullspace "
                "to bias and the whole term becomes uncommanded tool motion. "
                "ns_gain must be 0.0 unless the arm has MORE THAN six joints."
            )
        if robot.ns_gain != 0.0 and robot.w_rot < 1.0:
            # A warning, not an error: it is a leak, not a category mistake. The
            # damped projector leaks as lambda^2/sigma^2, and w_rot scales the
            # rotation rows and shrinks sigma with them -- 0.55 % at w_rot = 1.0
            # against 27.6 % at 0.05, on the same arm.
            warnings.warn(
                f"ROBOTS[{i}] ('{robot.tcp_body}') has ns_gain="
                f"{robot.ns_gain} with w_rot={robot.w_rot} < 1.0. The damped "
                "projector leaks as lambda^2/sigma^2 and w_rot shrinks sigma, so "
                "the nullspace bias will show up as uncommanded tool motion. "
                "Measure a commanded PURE TRANSLATION and look at the tool "
                "rotation, not at a position median -- a position median cannot "
                "see it.",
                stacklevel=2,
            )
        if robot.gripper_closed == robot.gripper_open:
            raise ValueError(
                f"ROBOTS[{i}] ('{robot.tcp_body}') has gripper_closed == "
                "gripper_open, so the trigger maps to a constant and the jaw "
                "never moves."
            )


_validate(ROBOTS)


def robot_probe(model) -> Robot:
    """Identify the loaded model. Exactly one ``tcp_body`` must resolve.

    THE ROBOT IS PROBED AND NEVER NAMED: no ``--robot`` flag, no robot id
    crossing any boundary, and no way for a caller to assert a robot the model is
    not.

    Probes EVERY row rather than returning the first hit, so an ambiguous table
    is a loud failure at load instead of an arm silently driving with another
    arm's gains. Both failure messages name the discriminator, because the fix is
    always in the ``tcp_body`` column.

    Measured on the shipping table: the two rows share zero names -- 0 of the 12
    joint names they carry between them (7 + 5) and 0 of the 2 actuator names --
    so ``tcp_body`` alone separates them.
    """
    matched = [
        robot
        for robot in ROBOTS
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, robot.tcp_body) >= 0
    ]
    if len(matched) == 1:
        return matched[0]
    if not matched:
        raise ValueError(
            f"no robot in robot_spec.ROBOTS matches this model -- none of its "
            f"{len(ROBOTS)} tcp_body names "
            f"({', '.join(repr(r.tcp_body) for r in ROBOTS)}) resolve against it. "
            "Either this scene's robot has no table row, or its wrapper XML did "
            "not include the robot."
        )
    raise ValueError(
        f"{len(matched)} of {len(ROBOTS)} robots in robot_spec.ROBOTS match this "
        f"model (tcp_body {', '.join(repr(r.tcp_body) for r in matched)}). The "
        "table no longer discriminates, so the gains would be a guess; give the "
        "rows distinct tcp_body names."
    )
