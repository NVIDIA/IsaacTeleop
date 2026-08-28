# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The robot twin's MuJoCo must be invisible to the process it runs in.

Everything here is about one failure: a user's ``mujoco`` wheel and ours resolving to each
other. It is silent when it happens -- no import error, no version warning, just the wrong
library executing -- so these are the assertions that have to catch it.

Every one of them runs against the module that ships. A test-only extension carrying a
second copy of the recipe would pass while the shipped one regressed, and its share of
these assertions would be weaker: ``--version-script`` has nothing to hide in a module
that links no static archive, and the shipped one links ``cudart_static``.
"""

import ctypes
import os
import pathlib
import subprocess
import sys

import pytest

TWIN_DIR = os.environ.get("ISAACTELEOP_ROBOT_TWIN_DIR")
INTERNAL_VERSION = os.environ.get("ISAACTELEOP_MUJOCO_VERSION")
HERE = pathlib.Path(__file__).parent

pytestmark = pytest.mark.skipif(
    not TWIN_DIR or not INTERNAL_VERSION,
    reason="run through ctest, which sets ISAACTELEOP_ROBOT_TWIN_DIR and ISAACTELEOP_MUJOCO_VERSION",
)


@pytest.fixture(scope="module")
def twin_dir():
    return pathlib.Path(TWIN_DIR)


@pytest.fixture(scope="module")
def twin_so(twin_dir):
    matches = sorted(twin_dir.glob("_robot_twin*.so"))
    assert len(matches) == 1, f"expected one twin extension, found {matches}"
    return matches[0]


@pytest.fixture(scope="module")
def private_mujoco(twin_dir):
    """The copy the twin dlopens: staged beside it by deps/third_party/Mujoco.cmake."""
    return twin_dir / "libisaacteleop_mujoco.so"


@pytest.fixture(scope="module")
def twin(twin_dir):
    """The shipped extension, imported the way the wheel exposes it."""
    sys.path.insert(0, str(twin_dir))
    import _robot_twin

    return _robot_twin


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


# ---------------------------------------------------------------- what the linker did


def test_the_extension_exports_only_its_entry_point(twin_so):
    """The one assertion that stops a silent interposition regressing back in.

    MuJoCo compiles its ~700 ``mj*`` at default visibility, so anything that put them in
    this module's dynamic table would offer them to the whole process. Measured: the
    version script takes this from 11 exports to 1.
    """
    assert _dynamic_symbols(twin_so) == ["PyInit__robot_twin"]


def test_nothing_links_libmujoco(twin_so):
    """The load-bearing one: an undefined mj* is what a foreign libmujoco answers.

    MuJoCo is reached through dlopen/dlsym instead, so there is no NEEDED entry and no
    symbol for the global scope to resolve.
    """
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


def test_the_private_mujoco_ships_beside_the_extension(private_mujoco):
    """mj_api.cpp opens it by the module's own directory, so the wheel must stage it there.

    A plain file, not a symlink to a versioned one, because wheels do not carry symlinks.
    """
    assert private_mujoco.is_file() and not private_mujoco.is_symlink()


def test_the_private_mujoco_ships_under_its_own_name(private_mujoco):
    """A SONAME of libmujoco.so.3.x is what the wheel's own extensions resolve.

    They carry DT_NEEDED on it, and the loader satisfies that from whatever is already
    loaded under that SONAME -- so an unrenamed copy of ours, loaded first, would answer
    the user's ``import mujoco`` and be the only libmujoco the process maps.
    """
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
    """-Wl,-Bsymbolic, and nothing else here would catch its absence.

    Without it, one MuJoCo function calling another goes through the global scope, and a
    user's libmujoco sitting there answers with a differently laid out mjData. Measured:
    with the wheel loaded RTLD_GLOBAL, a build without this dies at import inside
    MuJoCo's own resource registry -- but under the default RTLD_LOCAL it passes every
    other test in this file.
    """
    out = subprocess.run(
        ["readelf", "-d", "-W", str(private_mujoco)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "SYMBOLIC" in out, out


# ---------------------------------------------------------------- two copies, one process


def test_a_foreign_mujoco_shares_the_process(twin):
    """Import order is the app's: the wheel first, as a user's own code would."""
    import mujoco

    assert mujoco.mj_versionString() != INTERNAL_VERSION, (
        "the dev extra pins the same version the twin builds, so this proves nothing"
    )
    assert twin.mujoco_version() == INTERNAL_VERSION


def test_both_copies_still_work(twin):
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(HERE / "model.xml"))
    mujoco.mj_forward(model, mujoco.MjData(model))
    assert twin.Scene(str(HERE / "model.xml")).ngeom > 0


def test_rtld_global_does_not_interpose_us(twin_dir):
    """The failure mode the hiding exists for, in the configuration that provokes it.

    Extensions load RTLD_LOCAL by default, so an unhidden build passes every test above
    and only breaks once something else in the process flips the flag.
    """
    script = (
        "import ctypes, sys;"
        f"sys.path.insert(0, {str(twin_dir)!r});"
        "sys.setdlopenflags(sys.getdlopenflags() | ctypes.RTLD_GLOBAL);"
        "import mujoco, _robot_twin;"
        "print(mujoco.mj_versionString(), _robot_twin.mujoco_version())"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.split()
    assert out[1] == INTERNAL_VERSION, f"interposed by the wheel's {out[0]}"


def test_mj_symbols_are_absent_from_the_global_namespace(twin):
    """Nothing may satisfy an mj* lookup out of our extension."""
    with pytest.raises(AttributeError):
        ctypes.CDLL(None).mj_versionString


# ---------------------------------------------------------------- the error hooks


def _our_mujoco(twin_dir):
    """A handle on the twin's own copy.

    The twin already dlopened this exact file, and glibc dedupes a dlopen by inode, so
    this is that mapping rather than a third one.
    """
    return ctypes.CDLL(
        str(twin_dir / "libisaacteleop_mujoco.so"), mode=ctypes.RTLD_LOCAL
    )


def test_the_wheels_error_hook_does_not_bind_ours(twin, twin_dir):
    """``mju_user_error`` is a plain global per libmujoco copy, not shared state.

    Ours carries mj_guard.cpp's handler because the module initialiser installed it;
    the wheel's is whatever the wheel's own user set, and setting one cannot reach the
    other.
    """
    import mujoco

    mujoco.set_mju_user_warning(lambda _msg: None)
    wheel_lib = (
        pathlib.Path(mujoco.__file__).parent
        / f"libmujoco.so.{mujoco.mj_versionString()}"
    )
    ours = ctypes.c_void_p.in_dll(_our_mujoco(twin_dir), "mju_user_error").value
    theirs = ctypes.c_void_p.in_dll(
        ctypes.CDLL(str(wheel_lib), mode=ctypes.RTLD_LOCAL), "mju_user_error"
    ).value
    assert ours, "install_mujoco_handlers() did not reach the twin's own copy"
    assert ours != theirs


def test_an_unguarded_mujoco_error_aborts_rather_than_exits(twin_dir):
    """MuJoCo's default handler ends in exit(EXIT_FAILURE), taking the host with it.

    mj_guard.cpp replaces it. Outside a guarded call there is nowhere to land, so it says
    so and aborts -- which is what distinguishes it from the default, and from a handler
    that RETURNS and lets MuJoCo resume on state it has already declared invalid.
    """
    script = (
        "import ctypes, sys;"
        f"sys.path.insert(0, {str(twin_dir)!r});"
        "import _robot_twin;"
        f"ctypes.CDLL({str(twin_dir / 'libisaacteleop_mujoco.so')!r}).mju_error(b'deliberate')"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert "robot_twin: unguarded MuJoCo error: deliberate" in done.stderr, done.stderr
    assert done.returncode != 1, "exit(1) is MuJoCo's default handler, not ours"
