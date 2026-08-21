# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The robot twin's MuJoCo must be invisible to the process it runs in.

Everything here is about one failure: a user's ``mujoco`` wheel and ours resolving to each
other. It is silent when it happens -- no import error, no version warning, just the wrong
library executing -- so these are the assertions that have to catch it.
"""

import ctypes
import os
import pathlib
import subprocess
import sys

import pytest

PROBE_DIR = os.environ.get("MUJOCO_PROBE_DIR")
TWIN_DIR = os.environ.get("ISAACTELEOP_ROBOT_TWIN_DIR")
INTERNAL_VERSION = os.environ.get("ISAACTELEOP_MUJOCO_VERSION")
HERE = pathlib.Path(__file__).parent

pytestmark = pytest.mark.skipif(
    not PROBE_DIR or not INTERNAL_VERSION,
    reason="run through ctest, which sets MUJOCO_PROBE_DIR and ISAACTELEOP_MUJOCO_VERSION",
)


@pytest.fixture(scope="module")
def probe():
    sys.path.insert(0, PROBE_DIR)
    import _mujoco_probe

    return _mujoco_probe


@pytest.fixture(scope="module")
def probe_so():
    matches = sorted(pathlib.Path(PROBE_DIR).glob("_mujoco_probe*.so"))
    assert len(matches) == 1, f"expected one probe extension, found {matches}"
    return matches[0]


def _dynamic_symbols(so):
    out = subprocess.run(
        ["readelf", "--dyn-syms", "-W", str(so)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = []
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[4] in ("GLOBAL", "WEAK") and fields[6] != "UND":
            names.append(fields[7].split("@")[0])
    return names


def test_the_extension_exports_only_its_entry_point(probe_so):
    """The one assertion that stops a silent interposition regressing back in.

    MuJoCo compiles its ~700 ``mj*`` at default visibility, so anything that put them in
    this module's dynamic table would offer them to the whole process.
    """
    assert _dynamic_symbols(probe_so) == ["PyInit__mujoco_probe"]


def test_nothing_links_libmujoco(probe_so):
    """The load-bearing one: an undefined mj* is what a foreign libmujoco answers.

    MuJoCo is reached through dlopen/dlsym instead, so there is no NEEDED entry and no
    symbol for the global scope to resolve.
    """
    out = subprocess.run(
        ["readelf", "-d", str(probe_so)], capture_output=True, text=True, check=True
    ).stdout
    assert "mujoco" not in out


@pytest.fixture(scope="module")
def private_mujoco(probe_so):
    """The copy the probe dlopens: staged beside it by cmake/Mujoco.cmake."""
    return probe_so.parent / "libisaacteleop_mujoco.so"


def test_the_private_mujoco_ships_under_its_own_name(private_mujoco):
    """A SONAME of libmujoco.so.3.x would be deduped against the user's by the loader.

    A plain file, not a symlink to a versioned one, because wheels do not carry symlinks.
    """
    assert private_mujoco.is_file() and not private_mujoco.is_symlink()
    out = subprocess.run(
        ["readelf", "-d", "-W", str(private_mujoco)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    soname = [line for line in out.splitlines() if "SONAME" in line]
    assert len(soname) == 1, out
    assert "libisaacteleop_mujoco.so" in soname[0], soname


def test_the_private_mujoco_binds_its_own_calls(private_mujoco):
    """-Wl,-Bsymbolic, and nothing above would catch its absence.

    Without it, one MuJoCo function calling another goes through the global scope, and a
    user's libmujoco sitting there answers with a differently laid out mjData. The entry
    points this module resolves would still be ours.
    """
    out = subprocess.run(
        ["readelf", "-d", "-W", str(private_mujoco)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "SYMBOLIC" in out, out


def test_a_foreign_mujoco_shares_the_process(probe):
    """Import order is the app's: the wheel first, as a user's own code would."""
    import mujoco

    assert mujoco.mj_versionString() != INTERNAL_VERSION, (
        "the dev extra pins the same version the twin builds, so this proves nothing"
    )
    assert probe.version() == INTERNAL_VERSION


def test_both_copies_still_work(probe):
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(HERE / "model.xml"))
    mujoco.mj_forward(model, mujoco.MjData(model))
    assert probe.scene_geoms(str(HERE / "model.xml")) > 0


def test_mujoco_errors_recover_instead_of_exiting(probe):
    """MuJoCo's default handler ends in exit(EXIT_FAILURE), taking the host with it."""
    assert probe.recovered_message() == "mujoco: probe: deliberate"


def test_the_wheels_error_hook_does_not_bind_ours(probe):
    """``mju_user_error`` is a plain global per libmujoco copy, not shared state."""
    import mujoco

    mujoco.set_mju_user_warning(lambda _msg: None)
    assert probe.recovered_message() == "mujoco: probe: deliberate"


def test_rtld_global_does_not_interpose_us():
    """The failure mode the hiding exists for, in the configuration that provokes it.

    Extensions load RTLD_LOCAL by default, so an unhidden build passes every test above
    and only breaks once something else in the process flips the flag.
    """
    script = (
        "import ctypes, sys;"
        f"sys.path.insert(0, {PROBE_DIR!r});"
        "sys.setdlopenflags(sys.getdlopenflags() | ctypes.RTLD_GLOBAL);"
        "import mujoco, _mujoco_probe;"
        "print(mujoco.mj_versionString(), _mujoco_probe.version())"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.split()
    assert out[1] == INTERNAL_VERSION, f"interposed by the wheel's {out[0]}"


def test_mj_symbols_are_absent_from_the_global_namespace(probe):
    """Nothing may satisfy an mj* lookup out of our extension."""
    with pytest.raises(AttributeError):
        ctypes.CDLL(None).mj_versionString


# ---------------------------------------------------------------- the shipped module


@pytest.fixture(scope="module")
def twin_so():
    if not TWIN_DIR:
        pytest.skip("run through ctest, which sets ISAACTELEOP_ROBOT_TWIN_DIR")
    matches = sorted(pathlib.Path(TWIN_DIR).glob("_robot_twin*.so"))
    if not matches:
        pytest.skip(f"no _robot_twin*.so staged in {TWIN_DIR}")
    assert len(matches) == 1, f"expected one twin extension, found {matches}"
    return matches[0]


def test_the_shipped_twin_exports_only_its_entry_point(twin_so):
    """The probe above proves the recipe; this proves the wheel actually applied it.

    Without it the two can drift -- a link flag dropped from one CMakeLists and not the
    other -- and the failure is a silent interposition, not a build error.
    """
    assert _dynamic_symbols(twin_so) == ["PyInit__robot_twin"]


def test_the_shipped_twin_ships_its_mujoco_beside_itself(twin_so):
    """mj_api.cpp opens it by the module's own directory, so the wheel must stage it there."""
    private = twin_so.parent / "libisaacteleop_mujoco.so"
    assert private.is_file() and not private.is_symlink()


def test_the_shipped_twin_links_no_libmujoco(twin_so):
    """A NEEDED entry would put the SONAME back on the wheel's dependency graph."""
    out = subprocess.run(
        ["readelf", "-d", "-W", str(twin_so)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    needed = [line for line in out.splitlines() if "(NEEDED)" in line]
    assert not [line for line in needed if "mujoco" in line], needed
    # Nor on EGL or GL: both are dlopened, so a machine without them still imports.
    assert not [line for line in needed if "EGL" in line or "libGL" in line], needed
