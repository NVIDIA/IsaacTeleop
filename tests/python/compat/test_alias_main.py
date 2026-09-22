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

#: A plain module with an `if __name__ == "__main__"` guard, documented at
#: docs/source/references/oob_teleop_control.rst. runpy never recurses here, it
#: asks the loader for a code object -- so a loader that only declines to serve
#: `.__main__` breaks this shipped command. Its exit code depends on whether a
#: headset is attached, so the assertion is that both names agree.
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


def _nested_importer(tmp_path):
    """An app whose *dependency* imports the alias, which is the shape that takes
    the print branch: the default filters only surface a DeprecationWarning raised
    from ``__main__``."""
    (tmp_path / "vendor.py").write_text("import isaacteleop  # noqa: F401\n")
    (tmp_path / "app.py").write_text("import vendor  # noqa: F401\n")
    return tmp_path / "app.py", tmp_path / "vendor.py"


@pytest.mark.parametrize("module,args", ENTRY_POINTS)
def test_the_alias_and_the_real_name_behave_identically(module, args):
    old = _run(["-m", f"isaacteleop.{module}", *args])
    new = _run(["-m", f"isaaccapture.{module}", *args])
    assert old.returncode == 0, old.stderr
    assert old.returncode == new.returncode
    assert old.stdout == new.stdout


def test_a_plain_module_entry_point_still_runs_through_the_alias():
    old = _run(["-m", f"isaacteleop.{PLAIN_MODULE}"])
    new = _run(["-m", f"isaaccapture.{PLAIN_MODULE}"])
    assert old.returncode == new.returncode
    assert old.stdout == new.stdout
    # The decline design fails here with `'_Loader' object has no attribute
    # 'get_code'`, which is how this module settled the loader's surface.
    assert "get_code" not in old.stderr
    without_notice = [ln for ln in old.stderr.splitlines() if NOTICE_MARK not in ln]
    assert without_notice == new.stderr.splitlines()


@pytest.mark.parametrize("module,args", ENTRY_POINTS)
def test_the_notice_is_emitted_exactly_once(module, args):
    """Default filters drop a DeprecationWarning raised from importlib, which is
    every `python -m`, so the stderr line is what actually reaches the operator."""
    result = _run(["-m", f"isaacteleop.{module}", *args])
    assert result.stderr.count(NOTICE_MARK) == 1


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
    """`-W error::DeprecationWarning` is how a downstream proves it has migrated.

    A finder installed before the notice raises survives the raise, so the second
    import binds isaaccapture silently and the proof is worthless -- and the shape
    at Isaac Sim's teleop_manager.py:676 (`except ImportError`) turns the fatal
    deprecation into a pass.
    """
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
    """Both still work now that the guard probes the machinery instead of reading
    ``sys.warnoptions``: each moves an ignore filter ahead of PEP 565's
    ``default::DeprecationWarning:__main__``, which is what the guard looks for."""
    result = _run(argv, extra_env=env)
    assert result.returncode == 0
    assert NOTICE_MARK not in result.stderr


@pytest.mark.parametrize(
    "silencer",
    [
        "warnings.simplefilter('ignore', DeprecationWarning)",
        "warnings.filterwarnings('ignore', category=DeprecationWarning)",
    ],
)
def test_a_programmatic_silence_request_is_honoured(tmp_path, silencer):
    """Neither call reaches ``sys.warnoptions``, so a guard that reads it prints
    over both. The nested importer is the shape that takes the print branch."""
    app, _ = _nested_importer(tmp_path)
    app.write_text(f"import warnings\n{silencer}\nimport vendor  # noqa: F401\n")

    result = _run([str(app)])
    assert result.returncode == 0, result.stderr
    assert NOTICE_MARK not in result.stderr


def test_a_pytest_ini_filter_is_honoured(tmp_path):
    """The config the population being asked to migrate actually runs.

    ``filterwarnings`` routes through ``warnings.filterwarnings``, so it is
    invisible to ``sys.warnoptions`` -- and pytest applies it around collection,
    where a downstream's module-level ``import isaacteleop`` runs. ``-s``, because
    otherwise pytest captures the very stderr under test.
    """
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nfilterwarnings =\n    ignore::DeprecationWarning\n"
    )
    (tmp_path / "test_downstream.py").write_text(
        "import isaacteleop  # noqa: F401\n\n\ndef test_ok():\n    pass\n"
    )

    result = _run(["-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", str(tmp_path)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert NOTICE_MARK not in result.stderr


def test_the_printed_notice_names_the_importing_line(tmp_path):
    """The located warning only reaches users who already enabled warnings; this
    branch is the one every non-`__main__` import takes, so "which of my modules
    imported this?" has to be answerable from it."""
    app, vendor = _nested_importer(tmp_path)
    result = _run([str(app)])

    assert result.returncode == 0, result.stderr
    assert NOTICE_MARK in result.stderr
    assert f"{vendor}:1: " in result.stderr


def test_the_printed_and_warned_locations_agree(tmp_path):
    """One resolution, two channels: the print branch re-uses the warnings
    machinery rather than walking the stack itself, so they cannot drift."""
    app, vendor = _nested_importer(tmp_path)
    printed = _run([str(app)])
    warned = _run(["-W", "always::DeprecationWarning", str(app)])

    assert f"{vendor}:1: " in printed.stderr
    assert f"{vendor}:1: " in warned.stderr
