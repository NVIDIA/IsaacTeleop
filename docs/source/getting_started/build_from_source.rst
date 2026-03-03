.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Build from Source
=================

This page describes how to build Isaac Teleop from source, including core libraries, plugins, and
examples. The instructions align with the project's CMake configuration and the CI workflow
(`build-ubuntu.yml`_ in the GitHub repository).

Prerequisites
-------------

- **CMake** 3.20 or higher
- **C++20** compatible compiler
- **Python** 3.10, 3.11, or 3.12 (default 3.11; see ``ISAAC_TELEOP_PYTHON_VERSION`` in root ``CMakeLists.txt``)
- **uv** for Python dependency management and managed Python
- **Internet connection** for downloading dependencies via CMake FetchContent

One time setup
--------------

Install build tools and dependencies, such as CMake, clang-format. See `build-ubuntu.yml`_ in the GitHub repository for
the list of dependencies. On **Ubuntu**, install build tools and clang-format:

.. code-block:: bash

   sudo apt-get update
   sudo apt-get install -y build-essential cmake libx11-dev clang-format-14 ccache

Our build system uses `uv`_ for Python version and dependency management. Install `uv`_ if not already installed:

.. code-block:: bash

   curl -LsSf https://astral.sh/uv/install.sh | sh

.. note::
   While the building system uses `uv`_, the final Python packages can be installed via any Python package manager
   such as `pip <https://pip.pypa.io/>`_ or `conda <https://conda.io/>`_.  The users of Isaac Teleop can choose to use
   any Python package manager that fits their needs.

C++ Formatting Enforcement (Linux)
----------------------------------

On Linux, **clang-format** is enforced by default; the build fails if formatting changes would be applied. The project
uses **clang-format-14** for consistent results across distributions (see ``cmake/ClangFormat.cmake``).

To disable enforcement, set ``ENABLE_CLANG_FORMAT_CHECK`` to ``OFF``:

.. code-block:: bash

   cmake -B build -DENABLE_CLANG_FORMAT_CHECK=OFF

Useful targets:

- ``clang_format_check`` — verifies formatting (part of ``ALL`` on Linux)
- ``clang_format_fix`` — applies formatting in place

.. code-block:: bash

   cmake --build build --target clang_format_check
   cmake --build build --target clang_format_fix

CMake: Configure and build
--------------------------

From the project root:

.. code-block:: bash

   cmake -B build
   cmake --build build
   cmake --install build

This will:

1. Fetch dependencies (OpenXR SDK, yaml-cpp, pybind11, FlatBuffers, MCAP, and optionally Catch2 for tests) via FetchContent in ``deps/third_party/CMakeLists.txt``
2. Build core C++ libraries (schema, oxr_utils, plugin_manager, oxr, pusherio, deviceio, mcap, etc.) and Python bindings
3. Build the Python wheel
4. Build examples (if enabled)
5. Install to ``./install`` (default prefix set in root ``CMakeLists.txt``)

Build options
-------------

CMake options (defined in root `CMakeLists.txt <https://github.com/NVIDIA/IsaacTeleop/blob/main/CMakeLists.txt>`_,
`SetupPython.cmake <https://github.com/NVIDIA/IsaacTeleop/blob/main/cmake/SetupPython.cmake>`_, and
`SetupHunter.cmake <https://github.com/NVIDIA/IsaacTeleop/blob/main/cmake/SetupHunter.cmake>`_):

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
     - ``3.11`` (3.10, 3.11, or 3.12)
   * - **Testing**
     - ``BUILD_TESTING``
     - ``ON``; enables CTest and Catch2
   * - **Clang-format check**
     - ``ENABLE_CLANG_FORMAT_CHECK``
     - ``ON`` on Linux

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

Build with a different Python version (must match a version supported by ``SetupPython.cmake``):

.. code-block:: bash

   cmake -B build -DISAAC_TELEOP_PYTHON_VERSION=3.12
   cmake --build build

Debug build:

.. code-block:: bash

   cmake -B build -DCMAKE_BUILD_TYPE=Debug
   cmake --build build

Build without examples:

.. code-block:: bash

   cmake -B build -DBUILD_EXAMPLES=OFF
   cmake --build build

Build without Python bindings:

.. code-block:: bash

   cmake -B build -DBUILD_PYTHON_BINDINGS=OFF
   cmake --build build

Build with OAK camera plugin (pulls Hunter/DepthAI):

.. code-block:: bash

   cmake -B build -DBUILD_PLUGIN_OAK_CAMERA=ON
   cmake --build build

Build only the teleop_ros2 example (e.g. for Docker, as in ``.github/workflows/build-ubuntu.yml`` teleop-ros2-docker job):

.. code-block:: bash

   cmake -B build -DBUILD_EXAMPLES=OFF -DBUILD_EXAMPLE_TELEOP_ROS2=ON
   cmake --build build

Clean rebuild:

.. code-block:: bash

   rm -rf build
   cmake -B build
   cmake --build build

Running tests
-------------

When ``BUILD_TESTING`` is ``ON``, CTest is enabled at the top level. Run all tests either via the CMake ``test`` target or with ``ctest``:

.. code-block:: bash

   cmake --build build --target test

   # Or with ctest (e.g. parallel, output on failure)
   ctest --test-dir build --output-on-failure --parallel

The CI uses ``ctest`` (see ``.github/workflows/build-ubuntu.yml``).

Project structure
-----------------

The layout below reflects the actual ``CMakeLists.txt`` hierarchy (root ``CMakeLists.txt`` and ``src/core/CMakeLists.txt``):

.. code-block:: text
   :class: code-100col

   IsaacTeleop/
   ├── CMakeLists.txt              # Top-level: deps, core, examples, plugins, etc.
   ├── cmake/
   │   ├── SetupHunter.cmake       # BUILD_PLUGINS, Hunter for OAK/DepthAI
   │   ├── SetupPython.cmake       # BUILD_PYTHON_BINDINGS, uv-managed Python
   │   ├── ClangFormat.cmake       # clang_format_check / clang_format_fix
   │   └── ...
   ├── deps/
   │   ├── CMakeLists.txt          # Adds third_party
   │   ├── third_party/CMakeLists.txt  # FetchContent: OpenXR, yaml-cpp, pybind11, etc.
   │   └── cloudxr/                # CloudXR (CI / optional)
   ├── src/core/
   │   ├── CMakeLists.txt          # Core options, subdirs in dependency order
   │   ├── schema/                 # FlatBuffer schemas and generated code
   │   ├── oxr_utils/              # Header-only OpenXR utilities
   │   ├── plugin_manager/         # Plugin manager (C++ and Python)
   │   ├── oxr/                    # OpenXR session management (C++ and Python)
   │   ├── pusherio/               # PusherIO (depends on oxr)
   │   ├── deviceio/               # Device I/O library (C++ and Python)
   │   ├── mcap/                   # MCAP recording (depends on deviceio)
   │   ├── retargeting_engine/     # Retargeting (Python)
   │   ├── retargeting_engine_ui/  # Retargeting UI (Python)
   │   ├── teleop_session_manager/ # Teleop session manager (Python)
   │   ├── cloudxr/                # CloudXR runtime helper (Python)
   │   └── python/                 # Python wheel packaging (when BUILD_PYTHON_BINDINGS=ON)
   ├── src/plugins/                # Built when BUILD_PLUGINS=ON
   │   ├── plugin_utils/
   │   ├── controller_synthetic_hands/
   │   ├── generic_3axis_pedal/
   │   ├── manus/
   │   └── oak/                    # When BUILD_PLUGIN_OAK_CAMERA=ON
   └── examples/
       ├── oxr/                    # OpenXR examples (C++ and Python)
       ├── retargeting/
       ├── teleop_session_manager/
       ├── teleop_ros2/
       ├── schemaio/
       └── native_openxr/

CMake integration
-----------------

The project uses a modern CMake target-based approach. Libraries export targets (e.g. OXR, DEVICEIO, schema); include directories are propagated. Package config files are generated for use after install. See the respective ``CMakeLists.txt`` in ``src/core`` and under ``examples/`` for target names and usage.

Using the Python wheel
----------------------

After building, install the wheel with ``uv`` or ``pip``:

.. code-block:: bash

   uv pip install isaacteleop --find-links=./install/wheels/ --reinstall

   # or
   pip install install/wheels/isaacteleop-*.whl

Output locations
----------------

After a successful build and install:

- **C++ libraries:** ``build/src/core/`` (and under each module)
- **Python wheel:** ``build/wheels/isaacteleop-*.whl``
- **Examples (binaries):** under ``build/examples/`` (e.g. ``build/examples/oxr/cpp/``)
- **Installed files:** ``install/`` (or your ``CMAKE_INSTALL_PREFIX``)
  - Libraries: ``install/lib/``
  - Headers: ``install/include/``
  - Wheels: ``install/wheels/``
  - Examples: ``install/examples/``

Troubleshooting
---------------

Dependencies fail to download
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FetchContent in ``deps/third_party/CMakeLists.txt`` requires network access. If downloads fail, check connectivity. Key repositories:

- OpenXR SDK: https://github.com/KhronosGroup/OpenXR-SDK.git
- pybind11: https://github.com/pybind/pybind11.git
- yaml-cpp: https://github.com/jbeder/yaml-cpp.git
- FlatBuffers, Catch2, MCAP: see ``deps/third_party/CMakeLists.txt`` for URLs and tags.

You can inspect the ``_deps`` directory in your build tree for fetch logs.

CMake can't find OpenXR
~~~~~~~~~~~~~~~~~~~~~~~

OpenXR is fetched automatically; it is not a system package. If configuration fails, try a clean configure:

.. code-block:: bash

   rm -rf build
   cmake -B build

Examples or tests can't find the library
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When building from the top-level, examples and tests use the build tree. Ensure you run ``cmake --build build`` from the project root and run executables from the build directory (or use ``cmake --install build`` and run from ``install/``).

uv or Python version
~~~~~~~~~~~~~~~~~~~~

``cmake/SetupPython.cmake`` requires **uv** and uses ``ISAAC_TELEOP_PYTHON_VERSION``. Install uv as in **Initial setup** and pass ``-DISAAC_TELEOP_PYTHON_VERSION=3.10`` (or 3.11, 3.12) if you need a specific version.

Reference
---------

- Root build and options: ``CMakeLists.txt``
- Core modules and options: ``src/core/CMakeLists.txt``
- Dependencies: ``deps/third_party/CMakeLists.txt``
- Python and uv: ``cmake/SetupPython.cmake``
- Plugins and Hunter: ``cmake/SetupHunter.cmake``
- CI (Ubuntu, matrix build_type/python_version/arch): ``.github/workflows/build-ubuntu.yml``


..
   References
.. _`uv`: https://docs.astral.sh/uv/
.. _`build-ubuntu.yml`: https://github.com/NVIDIA/IsaacTeleop/blob/main/.github/workflows/build-ubuntu.yml
