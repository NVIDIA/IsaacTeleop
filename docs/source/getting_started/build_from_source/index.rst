.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Build from Source
=================

This page describes how to build Isaac Teleop from source, including core libraries, plugins, and
examples. The instructions align with the project's CMake configuration and the CI workflow
(:code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>` in the GitHub repository).

.. contents:: Steps
   :local:
   :depth: 1

.. admonition:: Next Steps

   - To build and serve the **WebXR client** locally, see :doc:`webxr`.

Prerequisites
-------------

- **CMake** 3.20 or higher
- **C++20** compatible compiler
- **Python** 3.11, 3.12, or 3.13 (default 3.11; see ``ISAAC_TELEOP_PYTHON_VERSION`` in root ``CMakeLists.txt``)
- **uv** for Python dependency management and managed Python
- **Internet connection** for downloading dependencies via CMake FetchContent

.. _one-time-setup:

One time setup
--------------

Install build tools and dependencies, such as CMake, clang-format. See :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>` in the GitHub repository for
the list of dependencies. On **Ubuntu**, install build tools and clang-format:

.. code-block:: bash

   sudo apt-get update
   sudo apt-get install -y build-essential cmake libx11-dev clang-format-14 ccache patchelf

Runtime-only dependencies (needed to actually run teleop, not to build):

.. code-block:: bash

   # adb — required for OOB teleop (``--setup-oob``) to talk to the headset over USB.
   # coturn — required for USB-local mode (``--usb-local``); runs a local TURN server
   #          so WebRTC ICE can relay traffic from the headset to the CloudXR backend
   #          over the USB cable.
   sudo apt-get install -y android-tools-adb coturn

Our build system uses `uv`_ for Python version and dependency management. Install `uv`_ if not already installed:

.. code-block:: bash

   curl -LsSf https://astral.sh/uv/install.sh | sh

The installer drops ``uv`` in ``~/.local/bin``, which is not on ``PATH`` in most shells. Add it for
the current shell — and to your ``~/.bashrc`` to make it stick — or every ``uv`` command below
fails with ``uv: command not found``:

.. code-block:: bash

   export PATH="$HOME/.local/bin:$PATH"

.. note::
   While the build system uses `uv`_, the final Python packages can be installed via any Python package manager
   such as `pip <https://pip.pypa.io/>`_ or `conda <https://conda.io/>`_.

1. Clone the repository
-----------------------

.. code-block:: bash

   git clone https://github.com/NVIDIA/IsaacTeleop.git
   cd IsaacTeleop

.. note::
   Dependencies (OpenXR SDK, pybind11, yaml-cpp) are automatically downloaded
   during CMake configuration using FetchContent. No manual dependency installation or
   git submodule initialization is required.

Pre-download CloudXR SDK (Optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

   If you are using the default flow, skip this step. The
   :code-file:`CMakeLists.txt <src/core/cloudxr/python/CMakeLists.txt>`
   will automatically download the CloudXR SDK by calling the
   :code-file:`download_cloudxr_runtime_sdk.sh <scripts/download_cloudxr_runtime_sdk.sh>`
   script.

Sometimes NVIDIA might share early access CloudXR SDKs with you. In that case, you may get
tarballs such as:

- ``CloudXR-<version-for-runtime-sdk>-Linux-<arch>-sdk.tar.gz`` (CloudXR Runtime SDK)
- ``CloudXR-exp-<version-for-runtime-sdk>-Linux-<arch>-sdk.tar.gz`` (optional experimental
  runtime). Needed for Jetson Orin support (for example :doc:`/getting_started/televiz`)
  until the default runtime covers those platforms.
- ``nvidia-cloudxr-<version-for-web-sdk>.tgz`` (CloudXR Web SDK)

You can place them in the :code-file:`deps/cloudxr/` directory and update the ``deps/cloudxr/.env``
file to locally override the default version defined in :code-file:`deps/cloudxr/.env.default`,
like this:

.. code-block:: bash

   CXR_RUNTIME_SDK_VERSION=<version-for-runtime-sdk>
   CXR_WEB_SDK_VERSION=<version-for-web-sdk>

To package the experimental runtime into the wheel as ``isaacteleop.cloudxr_exp``, configure with
``-DENABLE_CLOUDXR_EXP_BUNDLE=ON``. Select it at runtime with ``ISAAC_TELEOP_CLOUDXR_EXP``.
See :ref:`dedicated-cloudxr-runtime`.

2. CMake: Configure and build
-----------------------------

From the project root, configure with a **preset** — there is one per supported
Python version (``py3.11`` … ``py3.13``; see :code-file:`CMakePresets.json`). A
preset selects the Python version and an isolated per-version build directory, so
different versions never share (and clobber) one configured CMake cache:

.. code-block:: bash

   cmake --preset py3.12                       # configure
   cmake --build --preset py3.12 --parallel    # build
   cmake --install build/cmake-cpython-312     # install

``cmake --preset py3.12`` is shorthand for the explicit configure it expands to —
an isolated build directory plus the Python version:

.. code-block:: bash

   cmake -B build/cmake-cpython-312 -DISAAC_TELEOP_PYTHON_VERSION=3.12

Add any other options as ``-D`` flags on the same line; a command-line ``-D``
overrides the preset (e.g. ``cmake --preset py3.12 -DCMAKE_BUILD_TYPE=Debug``).
Pick the preset that matches your interpreter rather than overriding
``ISAAC_TELEOP_PYTHON_VERSION`` by hand. (A bare ``cmake -B build`` still works
for a quick default build — Python 3.11 into ``./build`` — but the presets are
the recommended path.)

This will:

1. Fetch dependencies (OpenXR SDK, yaml-cpp, pybind11, FlatBuffers, MCAP, and optionally Catch2 for tests) via FetchContent in ``deps/third_party/CMakeLists.txt``
2. Build core C++ libraries (schema, oxr_utils, plugin_manager, oxr, pusherio, deviceio, mcap, etc.) and Python bindings
3. Build the Python wheel
4. Build examples (if enabled)
5. Install to ``./install`` (default prefix set in root ``CMakeLists.txt``)


C++ Formatting Enforcement (Linux)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On Linux, **clang-format** is enforced by default; the build fails if formatting changes would be applied. The project
uses **clang-format-14** for consistent results across distributions (see ``cmake/ClangFormat.cmake``).

To disable enforcement, set ``ENABLE_CLANG_FORMAT_CHECK`` to ``OFF``:

.. code-block:: bash

   cmake --preset py3.12 -DENABLE_CLANG_FORMAT_CHECK=OFF

Useful targets:

- ``clang_format_check`` — verifies formatting (part of ``ALL`` on Linux)
- ``clang_format_fix`` — applies formatting in place

.. code-block:: bash

   cmake --build --preset py3.12 --target clang_format_check
   cmake --build --preset py3.12 --target clang_format_fix

Other Build options
~~~~~~~~~~~~~~~~~~~

The CMake options (defined in root :code-file:`CMakeLists.txt` and :code-file:`cmake/SetupPython.cmake`):

.. list-table:: Common CMake Options
   :widths: 20 36 44
   :header-rows: 1

   * - Option
     - CMake flag
     - Default / Notes
   * - **Build type**
     - ``CMAKE_BUILD_TYPE``
     - ``Release`` or ``Debug``
   * - **Install prefix**
     - ``CMAKE_INSTALL_PREFIX``
     - ``./install``

.. list-table:: Common Isaac Teleop Options
   :widths: 24 36 40
   :header-rows: 1

   * - Option
     - CMake flag
     - Default / Notes
   * - **Examples**
     - ``BUILD_EXAMPLES``
     - ``ON``
   * - **Python bindings**
     - ``BUILD_PYTHON_BINDINGS``
     - ``ON``
   * - **Python version**
     - ``ISAAC_TELEOP_PYTHON_VERSION``
     - ``3.11`` (3.11, 3.12, or 3.13)
   * - **Testing**
     - ``BUILD_TESTING``
     - ``ON``; enables CTest and Catch2
   * - **Clang-format check**
     - ``ENABLE_CLANG_FORMAT_CHECK``
     - ``ON`` on Linux
   * - **Televiz visualization**
     - ``BUILD_VIZ``
     - Auto: ``ON`` when Vulkan, the CUDA Toolkit, and ``glslangValidator`` are detected, else ``OFF``. Force with ``-DBUILD_VIZ=ON`` / ``-DBUILD_VIZ=OFF``. (Most users don't need this — ``pip install isaacteleop`` already ships the compiled ``isaacteleop.viz`` module.)

.. list-table:: Plugin Specific Options
   :widths: 26 34 40
   :header-rows: 1

   * - Option
     - CMake flag
     - Default / Notes
   * - **Plugins master switch**
     - ``BUILD_PLUGINS``
     - ``ON``
   * - **OAK camera plugin**
     - ``BUILD_PLUGIN_OAK_CAMERA``
     - ``OFF``; requires Hunter/DepthAI when ``ON``
   * - **Teleop ROS2 example only**
     - ``BUILD_EXAMPLE_TELEOP_ROS2``
     - ``OFF``; when ``ON``, only ``examples/teleop_ros2`` (e.g. Docker)

Examples
~~~~~~~~

Build for a different Python version — use the matching preset (``py3.11``,
``py3.12``, ``py3.13``):

.. code-block:: bash

   cmake --preset py3.12
   cmake --build --preset py3.12 --parallel

Debug build:

.. code-block:: bash

   cmake --preset py3.12 -DCMAKE_BUILD_TYPE=Debug
   cmake --build --preset py3.12

Build without examples:

.. code-block:: bash

   cmake --preset py3.12 -DBUILD_EXAMPLES=OFF
   cmake --build --preset py3.12

Build without Python bindings:

.. code-block:: bash

   cmake --preset py3.12 -DBUILD_PYTHON_BINDINGS=OFF
   cmake --build --preset py3.12

Build with OAK camera plugin (pulls Hunter/DepthAI):

.. code-block:: bash

   cmake --preset py3.12 -DBUILD_PLUGIN_OAK_CAMERA=ON
   cmake --build --preset py3.12

Build only the teleop_ros2 example (e.g. for Docker, as in :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>` teleop-ros2-docker job):

.. code-block:: bash

   cmake --preset py3.12 -DBUILD_EXAMPLES=OFF -DBUILD_EXAMPLE_TELEOP_ROS2=ON
   cmake --build --preset py3.12

Clean rebuild (``--fresh`` wipes the preset's CMake cache and reconfigures):

.. code-block:: bash

   cmake --preset py3.12 --fresh
   cmake --build --preset py3.12

3. Running tests
----------------

When ``BUILD_TESTING`` is ``ON``, CTest is enabled at the top level. Run all tests either via the CMake ``test`` target or with ``ctest``:

.. code-block:: bash

   cmake --build --preset py3.12 --target test

   # Or with ctest (e.g. parallel, output on failure)
   ctest --test-dir build/cmake-cpython-312 --output-on-failure --parallel

The CI uses ``ctest`` (see :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>`).

4. Install the ``isaacteleop`` pip package
------------------------------------------

The wheels are built in the ``./install/wheels/`` directory. Install the package from the wheels.
Using ``pip``, you need to pass the ``--no-index`` option to automatically find the right wheel
based on the Python version.  Note that ``pip`` and ``uv pip`` has slightly different options.

.. code-block:: bash

   # Pass --no-index to use only wheels in ./install/wheels/;
   # Pass --force-reinstall to replace an existing install.
   pip install "isaacteleop[retargeters,cloudxr,ui]" --find-links=./install/wheels/ --no-index --force-reinstall

.. code-block:: bash

   # Pass --reinstall to replace an existing install.
   uv pip install "isaacteleop[retargeters,cloudxr,ui]" --find-links=./install/wheels/ --reinstall

Alternative: install directly from source with pip
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The repository also ships a root :code-file:`pyproject.toml` using the
`scikit-build-core <https://scikit-build-core.readthedocs.io/>`_ backend, which
drives the same top-level ``CMakeLists.txt``. This lets you build and install
with standard Python tooling, without running the ``cmake -B build`` steps
yourself; the classic flow above (which CI uses to produce ``install/wheels/`` and
the released wheels) is unchanged, so the two coexist.

.. code-block:: bash

   pip install .            # build + install the compiled wheel from source
   pip install -e .         # editable / developer install

.. note::

   The CMake build tree is kept under ``build/wheel-<cache-tag>/`` (e.g.
   ``build/wheel-cpython-311/``) — one per Python version, so different
   interpreters never share a configured CMake cache — instead of a temporary
   directory. Re-installs are therefore incremental. The classic CMake path uses
   sibling ``build/cmake-<cache-tag>/`` trees (via the presets below) with the same
   per-version tag, so the two never collide; ``build/`` is gitignored.

What this path does and how it differs from the classic flow:

- **Full build, no overrides.** The backend passes no ``cmake.define`` overrides,
  so ``BUILD_EXAMPLES``, ``BUILD_TESTING``, and ``BUILD_PLUGINS`` stay at their
  CMake defaults: a ``pip install`` builds the full default target — extensions,
  examples, C++ tests, and plugins (a plugin without its SDK skips gracefully). It
  installs only the ``isaacteleop_wheel`` and ``isaacteleop_binaries`` components,
  so C++ library/header install rules do not leak into the wheel.
- **clang-format is enforced.** Because the gate is left on, the build **fails** if
  ``clang-format-14`` is not installed or any C++ file is unformatted — a
  ``pip install`` therefore requires ``clang-format-14`` on Linux.
- **All executables on PATH.** Every executable built from ``src/`` and
  ``examples/`` — example programs, C++ test binaries, plugin tools
  (``oxr_simple_api_demo``, ``se3_printer``, ``schema_tests``, …) — is installed
  into the venv's ``bin/`` (the wheel's scripts scheme; see the executable-install
  loop in the root ``CMakeLists.txt``), so they are on ``PATH`` once the venv is
  active. They statically link the teleop core libraries, so they are
  self-contained. Shared libraries (Python extension modules, plugin ``.so``) are
  not executables and are **not** placed in ``bin/``.
- **ABI.** Extensions are compiled against the interpreter that runs the build
  (so the wheel's ABI tag matches) and against NumPy 2.x, so a single wheel works
  with both NumPy 1.x and 2.x at runtime.
- **No type stubs.** The pip-built wheel omits the ``.pyi`` stubs that the classic
  and released wheels ship (stub generation shells out to ``uv``, which is not
  guaranteed inside pip's build isolation). Imports and runtime behavior are
  unaffected.
- **Version.** The pip-facing version is derived from the ``VERSION`` file as
  ``MAJOR.MINOR+local`` — the same value the classic flow produces for a
  non-CI/local build. The pip path is a from-source/dev build, so it is always
  tagged ``+local``; the git-aware release versioning (tags, ``a1`` / ``rc1`` /
  ``.devN`` labels) stays with the classic flow via
  :code-file:`cmake/IsaacTeleopVersion.cmake`.

.. admonition:: Editable installs and iterating on pure-Python subpackages

   An editable install (``pip install -e .``) never recompiles on import. Pure-Python
   subpackages resolve straight to ``src/python/isaacteleop/``, so edits **take effect
   live** — a fresh interpreter is enough.

   Compiled extensions are the exception: ``.so``/``.pyd`` still come from the CMake
   build tree, so C++ changes need a ``cmake --build`` (or a re-run of
   ``pip install -e .``) first.

See :doc:`/references/build` for the full build-system reference.

.. admonition:: ``retargeters`` extra on aarch64 (Jetson / DGX)

   The full ``retargeters`` extra does **not** resolve on ``aarch64`` (some of its
   pinned dependencies have no aarch64 wheels). On Jetson/DGX-class robotics
   targets, install the ``retargeters-lite`` extra instead:

   .. code-block:: bash

      pip install "isaacteleop[retargeters-lite]"

.. toctree::
   :hidden:

   webxr

..
   References
.. _`uv`: https://docs.astral.sh/uv/
