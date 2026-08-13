# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# PythonTestVenv.cmake
# ==============================================================================
# Prepares the uv environment a directory's Python tests share.
#
# Each test_*.py is its own CTest entry running `uv run` in that directory, so
# they all drive one `.venv`. `uv run` syncs before it executes, and concurrent
# syncs of one environment are not safe, so a setup fixture syncs it once and
# the tests then run in parallel over a complete environment.
#
# `uv sync` is exact where `uv run` is not: the setup installs the union of
# every extra the directory's tests request, and a test that asks for a subset
# leaves the environment alone.
#
# Usage, from the directory that owns the environment:
#   isaac_teleop_python_test_venv_setup(<fixture> [<uv sync args>...])
#   isaac_teleop_python_test_venv_require(<fixture> <test> [<test>...])
# ==============================================================================

# Register the one-time `uv sync` for <fixture>. Trailing arguments go to
# `uv sync` (e.g. --extra dev --extra gpu).
function(isaac_teleop_python_test_venv_setup fixture)
    add_test(
        NAME "${fixture}_venv_setup"
        COMMAND uv sync --python ${ISAAC_TELEOP_PYTHON_VERSION} ${ARGN}
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
    set_tests_properties("${fixture}_venv_setup" PROPERTIES FIXTURES_SETUP "${fixture}_venv")
endfunction()

# Make the named tests wait for <fixture>. CTest schedules the setup even when
# only a dependent is selected, so `ctest -R <one-test>` still prepares it.
function(isaac_teleop_python_test_venv_require fixture)
    set_property(TEST ${ARGN} APPEND PROPERTY FIXTURES_REQUIRED "${fixture}_venv")
endfunction()
