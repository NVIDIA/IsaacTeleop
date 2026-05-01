Build System
============

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

When building from the top-level, examples and tests use the build tree. Ensure you run
``cmake --build build`` from the project root and run executables from the build directory (or use
``cmake --install build`` and run from ``install/``).

uv or Python version
~~~~~~~~~~~~~~~~~~~~

``cmake/SetupPython.cmake`` requires **uv** and uses ``ISAAC_TELEOP_PYTHON_VERSION``. Install uv as
in :ref:`One time setup <one-time-setup>` and pass ``-DISAAC_TELEOP_PYTHON_VERSION=3.10`` (or 3.11,
3.12) if you need a specific version.

Reference
---------

- Root build and options: ``CMakeLists.txt``
- Core modules and options: ``src/core/CMakeLists.txt``
- Dependencies: ``deps/third_party/CMakeLists.txt``
- Python and uv: ``cmake/SetupPython.cmake``
- Plugins and Hunter: ``cmake/SetupHunter.cmake``
- CI (Ubuntu, matrix build_type/python_version/arch): ``.github/workflows/build-ubuntu.yml``
