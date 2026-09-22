# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""`python -m` is the CLI -- there is no [project.scripts] anywhere in the repo.

Subprocesses, because runpy asks the *loader* for the code object and that path
only exists in a fresh interpreter.
"""

import os
import subprocess
import sys

import pytest

NOTICE_MARK = "renamed to 'isaaccapture'"

#: Packages. runpy reads submodule_search_locations and recurses into `.__main__`.
ENTRY_POINTS = [
    ("cloudxr", ["--help"]),
    ("cloudxr.service", ["run", "--help"]),
]

#: A plain module with an `if __name__ == "__main__"` guard: runpy never recurses,
#: it asks the loader for a code object. `--print-only` skips the adb probes, which
#: would otherwise open the WebXR client on any attached headset.
PLAIN_MODULE = "cloudxr.webclient"


def _run(args, extra_env=None):
    env = {**os.environ, **extra_env} if extra_env else None
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("module,args", ENTRY_POINTS)
def test_the_alias_and_the_real_name_behave_identically(module, args):
    old = _run(["-m", f"isaacteleop.{module}", *args])
    new = _run(["-m", f"isaaccapture.{module}", *args])
    assert old.returncode == 0, old.stderr
    assert old.returncode == new.returncode
    assert old.stdout == new.stdout


def test_a_plain_module_entry_point_still_runs_through_the_alias():
    old = _run(["-m", f"isaacteleop.{PLAIN_MODULE}", "--print-only"])
    new = _run(["-m", f"isaaccapture.{PLAIN_MODULE}", "--print-only"])
    assert old.returncode == new.returncode
    assert old.stdout == new.stdout
    # A loader that declines `.__main__` fails here with `'_Loader' object has no
    # attribute 'get_code'`.
    assert "get_code" not in old.stderr
    without_notice = [ln for ln in old.stderr.splitlines() if NOTICE_MARK not in ln]
    assert without_notice == new.stderr.splitlines()


def test_the_new_name_alone_says_nothing():
    """The library must not trip its own deprecation warning."""
    result = _run(["-c", "import isaaccapture"])
    assert result.returncode == 0
    assert result.stderr == ""


def test_an_error_filter_raises_and_does_not_also_print():
    result = _run(["-W", "error::DeprecationWarning", "-c", "import isaacteleop"])
    assert result.returncode == 1
    assert "DeprecationWarning" in result.stderr


#: Imports twice, reporting whether each raised and what is left on sys.meta_path.
REPEAT_IMPORT = """
import sys

for attempt in (1, 2):
    try:
        import isaacteleop
    except DeprecationWarning:
        print(f"{attempt} raised")
    else:
        print(f"{attempt} imported")
    sys.modules.pop("isaacteleop", None)
print(sum(1 for f in sys.meta_path if type(f).__name__ == "_AliasFinder"))
"""


def test_an_error_filter_raises_on_the_repeat_import_too():
    """A finder installed before the notice raises would survive the raise, and the
    second import would then bind isaaccapture silently -- so `-W error` could not
    be used to prove a downstream has migrated."""
    result = _run(["-W", "error::DeprecationWarning", "-c", REPEAT_IMPORT])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1 raised", "2 raised", "0"]


@pytest.mark.parametrize(
    "argv,env",
    [
        (["-W", "ignore::DeprecationWarning", "-c", "import isaacteleop"], None),
        (
            ["-c", "import isaacteleop"],
            {"PYTHONWARNINGS": "ignore::DeprecationWarning"},
        ),
    ],
)
def test_an_explicit_silence_request_is_honoured(argv, env):
    result = _run(argv, extra_env=env)
    assert result.returncode == 0
    assert NOTICE_MARK not in result.stderr
