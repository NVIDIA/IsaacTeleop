# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Python wheel packaging (combines OXR, DEVICEIO, MCAP, PluginManager, and Schema modules).


# Opt-in: bundle deps/v2d/src/robotic_grounding/ into the wheel so
# `pip install isaacteleop[grounding]` resolves the Sharpa retargeter.
# Populate the source via scripts/setup_v2d_src.sh first; then configure
# with -DBUNDLE_ROBOTIC_GROUNDING=TRUE. Default OFF -- forks / OSS builds
# produce a wheel without robotic_grounding, and Sharpa imports skip.
option(BUNDLE_ROBOTIC_GROUNDING "Bundle V2D's robotic_grounding into the wheel" OFF)

# pyproject.toml.in discovers packages from the staged tree via
# [tool.setuptools.packages.find], so viz and robotic_grounding ship exactly when
# they were staged; the template carries no per-configuration substitutions.
set(ROBOTIC_GROUNDING_SRC "${CMAKE_SOURCE_DIR}/deps/v2d/src/robotic_grounding")
if(BUNDLE_ROBOTIC_GROUNDING)
    if(NOT EXISTS "${ROBOTIC_GROUNDING_SRC}/__init__.py")
        message(FATAL_ERROR
            "BUNDLE_ROBOTIC_GROUNDING=TRUE but ${ROBOTIC_GROUNDING_SRC}/ "
            "is missing. Run scripts/setup_v2d_src.sh first.")
    endif()
    message(STATUS "[grounding] bundling robotic_grounding/ from ${ROBOTIC_GROUNDING_SRC}")
endif()

# Generate pyproject.toml from template with ISAAC_TELEOP_PYPROJECT_VERSION
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml.in"
    "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml"
    @ONLY
)

# After building modules, create the Python package structure.
add_custom_target(python_package ALL
    # The isaacteleop/ subtree itself is staged by src/python (pure Python),
    # by each pybind module's LIBRARY_OUTPUT_DIRECTORY (.so/.pyd) and by
    # src/core/cloudxr/python (vendored runtime). Only the staging root, which
    # holds the setuptools project files below, is created here.
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_BINARY_DIR}/pyproject.toml" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/MANIFEST.in" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/setup.py" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_SOURCE_DIR}/README.md" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/README.md"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-dev.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-ui.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-cloudxr.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-retargeters.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-retargeters-lite.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-grounding.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/requirements-wuji.txt" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/"
    DEPENDS deviceio_trackers_py deviceio_session_py oxr_py plugin_manager_py schema_py isaacteleop_python cloudxr_python
    COMMENT "Preparing Python package structure"
)

# viz_py only exists when BUILD_VIZ=ON. Use add_dependencies (not a
# DEPENDS genex) so the build-order constraint is unconditional under
# all generators — Windows ninja runs the wheel build in parallel
# with viz_py's link otherwise and trips a "Permission denied" race
# on the .pyd file.
if(BUILD_VIZ)
    add_dependencies(python_package viz_py)
endif()

# When deps/v2d/src/robotic_grounding/ is populated (script or CI action),
# stage it into the wheel staging dir so the resulting Teleop wheel ships
# robotic_grounding alongside isaacteleop.
if(BUNDLE_ROBOTIC_GROUNDING)
    add_custom_command(TARGET python_package POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E rm -rf
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/robotic_grounding"
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${ROBOTIC_GROUNDING_SRC}"
            "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>/robotic_grounding"
        COMMENT "Bundling robotic_grounding/ into wheel staging dir for [grounding] extra"
    )
endif()

# Generate Python type stubs (.pyi) for IDE intellisense
# Uses the same Python version that built the .so files (via uv --python)
# Each module is processed separately to avoid import chain issues
set(STUBGEN_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/generate_stubs.py")
set(STUBGEN_PYPROJECT "${CMAKE_CURRENT_SOURCE_DIR}/stubgen_pyproject.toml")
set(STUBGEN_PACKAGE_DIR "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>")
set(PY_TYPED_MARKER "${STUBGEN_PACKAGE_DIR}/isaacteleop/py.typed")

add_custom_command(
    OUTPUT "${PY_TYPED_MARKER}"
    COMMAND ${CMAKE_COMMAND} -E echo "Generating Python type stubs..."

    # Copy stubgen pyproject.toml to build directory for uv to use
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/stubgen"
    COMMAND ${CMAKE_COMMAND} -E copy "${STUBGEN_PYPROJECT}" "${CMAKE_BINARY_DIR}/stubgen/pyproject.toml"

    # Generate stubs for each pybind11 module using the stubgen pyproject.toml
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.deviceio_trackers._deviceio_trackers "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.deviceio_session._deviceio_session "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.oxr._oxr "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.plugin_manager._plugin_manager "${STUBGEN_PACKAGE_DIR}"
    COMMAND uv run --project "${CMAKE_BINARY_DIR}/stubgen" --python ${ISAAC_TELEOP_PYTHON_VERSION}
        python "${STUBGEN_SCRIPT}" isaacteleop.schema._schema "${STUBGEN_PACKAGE_DIR}"

    # Create py.typed marker file (PEP 561) - also serves as build stamp
    COMMAND ${CMAKE_COMMAND} -E touch "${PY_TYPED_MARKER}"
    DEPENDS python_package "${STUBGEN_SCRIPT}" "${STUBGEN_PYPROJECT}"
            $<TARGET_FILE:deviceio_trackers_py>
            $<TARGET_FILE:deviceio_session_py>
            $<TARGET_FILE:oxr_py>
            $<TARGET_FILE:plugin_manager_py>
            $<TARGET_FILE:schema_py>
            # viz_py's .pyd file as a file-level dependency when BUILD_VIZ=ON
            # — keeps the wheel build from racing the link. Empty otherwise.
            $<$<BOOL:${BUILD_VIZ}>:$<TARGET_FILE:viz_py>>
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Generating .pyi stub files for isaacteleop modules"
)

add_custom_target(python_stubs
    DEPENDS "${PY_TYPED_MARKER}"
    SOURCES "${STUBGEN_SCRIPT}" "${STUBGEN_PYPROJECT}"
)

# Custom target to build the wheel using uv (classic `cmake -B build` flow only).
# Depends on python_stubs to ensure py.typed marker and .pyi files are present.
# Gated to non-SKBUILD: under scikit-build-core, pip already owns wheel assembly,
# so this ALL target must NOT run -- otherwise building the default target would
# trigger a nested `uv build` inside the pip build.
if(NOT SKBUILD)
    add_custom_target(python_wheel ALL
        COMMAND ${CMAKE_COMMAND} -E echo "Building Python wheel with uv..."
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
        COMMAND uv build --wheel --python ${ISAAC_TELEOP_PYTHON_VERSION}
                --out-dir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>" ||
                "${Python3_EXECUTABLE}" -m build --wheel
                --outdir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package/$<CONFIG>"
        DEPENDS python_stubs
        WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
        COMMENT "Building Python wheel with uv (fallback to python -m build)"
    )
endif()

# Install the wheel built by the classic `cmake -B build` flow. Under
# scikit-build-core (SKBUILD) the wheel is assembled by pip from the staged tree
# instead -- see the block below -- so this rule is skipped there.
if(NOT SKBUILD)
    install(DIRECTORY "${CMAKE_BINARY_DIR}/wheels/"
        DESTINATION wheels
        FILES_MATCHING PATTERN "*.whl"
    )
endif()

# ==============================================================================
# scikit-build-core (PEP 517/660) wheel packaging
# ==============================================================================
# When pip / `uv build` / `python -m build` drives the build through
# scikit-build-core, it builds the `python_package` target (see
# build.targets in the root pyproject.toml), which -- with its module
# dependencies -- produces the fully-staged package tree at
# python_package/<config>/isaacteleop/ (compiled .so via each module's
# LIBRARY_OUTPUT_DIRECTORY, pure-Python subpackages copied in, __init__.py files).
# This single install rule copies that tree into the wheel's platlib. It is
# tagged with the `isaacteleop_wheel` component, selected via install.components
# in pyproject.toml, so the project's C++ library/header/example install() rules
# do NOT leak into the wheel.
if(SKBUILD)
    # scikit-build-core uses a single-config generator (Ninja) with
    # cmake.build-type set, so CMAKE_BUILD_TYPE resolves the staging dir's
    # $<CONFIG>. install(DIRECTORY) does not evaluate generator expressions in its
    # source path, so use the concrete config; fall back to Release defensively.
    set(_it_wheel_config "${CMAKE_BUILD_TYPE}")
    if(NOT _it_wheel_config)
        set(_it_wheel_config "Release")
    endif()

    # This component ships ONLY build-produced files: the pybind11 extensions,
    # the generated .pyi stubs and py.typed marker, and the vendored CloudXR
    # runtime. Every authored .py reaches the wheel through wheel.packages in the
    # root pyproject.toml instead, which is what makes them source-resolved under
    # an editable install.
    #
    # The *.py exclusion is load-bearing, not hygiene. The editable finder
    # generated by scikit-build-core consults `known_wheel_files` BEFORE
    # `known_source_files`, so a .py shipped here would shadow the wheel.packages
    # mapping and silently serve the stale staged copy -- editing src/python
    # would appear to do nothing. `wheel.exclude` cannot substitute: scikit-build-
    # core documents that editable installs may not respect it.
    install(
        DIRECTORY "${CMAKE_BINARY_DIR}/python_package/${_it_wheel_config}/isaacteleop"
        DESTINATION "."
        COMPONENT isaacteleop_wheel
        USE_SOURCE_PERMISSIONS
        PATTERN "*.py" EXCLUDE
        PATTERN "__pycache__" EXCLUDE
    )
endif()
