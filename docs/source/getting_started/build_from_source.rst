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

Prerequisites
-------------

- **CMake** 3.20 or higher
- **C++20** compatible compiler
- **Python** 3.10, 3.11, or 3.12 (default 3.11; see ``ISAAC_TELEOP_PYTHON_VERSION`` in root ``CMakeLists.txt``)
- **uv** for Python dependency management and managed Python
- **Internet connection** for downloading dependencies via CMake FetchContent

.. _one-time-setup:

One time setup
--------------

Install build tools and dependencies, such as CMake, clang-format. See :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>` in the GitHub repository for
the list of dependencies. On **Ubuntu**, install build tools and clang-format:

.. code-block:: bash

   sudo apt-get update
   sudo apt-get install -y build-essential cmake libx11-dev clang-format-14 ccache

Our build system uses `uv`_ for Python version and dependency management. Install `uv`_ if not already installed:

.. code-block:: bash

   curl -LsSf https://astral.sh/uv/install.sh | sh

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

Sometimes NVIDIA might share early access CloudXR SDKs with you. In that case, you may get one of
the two tarballs:

- ``CloudXR-<version-for-runtime-sdk>-Linux-<arch>-sdk.tar.gz`` (CloudXR Runtime SDK)
- ``nvidia-cloudxr-<version-for-web-sdk>.tgz`` (CloudXR Web SDK)

You can place them in the :code-file:`deps/cloudxr/` directory and update the ``deps/cloudxr/.env``
file to locally override the default version defined in :code-file:`deps/cloudxr/.env.default`,
like this:

.. code-block:: bash

   CXR_RUNTIME_SDK_VERSION=<version-for-runtime-sdk>
   CXR_WEB_SDK_VERSION=<version-for-web-sdk>

2. CMake: Configure and build
-----------------------------

From the project root:

.. code-block:: bash

   cmake -B build
   cmake --build build --parallel
   cmake --install build

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

   cmake -B build -DENABLE_CLANG_FORMAT_CHECK=OFF

Useful targets:

- ``clang_format_check`` — verifies formatting (part of ``ALL`` on Linux)
- ``clang_format_fix`` — applies formatting in place

.. code-block:: bash

   cmake --build build --target clang_format_check
   cmake --build build --target clang_format_fix

Other Build options
~~~~~~~~~~~~~~~~~~~

The CMake options (defined in root :code-file:`CMakeLists.txt`, :code-file:`cmake/SetupPython.cmake`, and :code-file:`cmake/SetupHunter.cmake`):

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

Build only the teleop_ros2 example (e.g. for Docker, as in :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>` teleop-ros2-docker job):

.. code-block:: bash

   cmake -B build -DBUILD_EXAMPLES=OFF -DBUILD_EXAMPLE_TELEOP_ROS2=ON
   cmake --build build

Clean rebuild:

.. code-block:: bash

   rm -rf build
   cmake -B build
   cmake --build build

3. Running tests
----------------

When ``BUILD_TESTING`` is ``ON``, CTest is enabled at the top level. Run all tests either via the CMake ``test`` target or with ``ctest``:

.. code-block:: bash

   cmake --build build --target test

   # Or with ctest (e.g. parallel, output on failure)
   ctest --test-dir build --output-on-failure --parallel

The CI uses ``ctest`` (see :code-file:`build-ubuntu.yml <.github/workflows/build-ubuntu.yml>`).

4. Install the ``isaacteleop`` pip package
------------------------------------------

The wheels are built in the ``./install/wheels/`` directory. Install the package from the wheels.
Using ``pip``, you need to pass the ``--no-index`` option to automatically find the right wheel
based on the Python version.  Note that ``pip`` and ``uv pip`` has slightly different options.

.. code-block:: bash

   # Pass --no-index to use only wheels in ./install/wheels/;
   # Pass --force-reinstall to replace an existing install.
   pip install isaacteleop[retargeters,cloudxr,ui] --find-links=./install/wheels/ --no-index --force-reinstall

.. code-block:: bash

   # Pass --reinstall to replace an existing install.
   uv pip install isaacteleop[retargeters,cloudxr,ui] --find-links=./install/wheels/ --reinstall

..
   References
.. _`uv`: https://docs.astral.sh/uv/
