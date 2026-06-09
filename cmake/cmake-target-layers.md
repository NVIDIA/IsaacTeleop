<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CMake target dependency layers

Layered, **direct-dependency** view of this project's CMake targets, derived from live
CMake (`cmake --graphviz`). Targets are sorted into topological layers: a target sits one
layer above its deepest direct dependency, so no two targets in a layer depend on each
other and dependencies always point to lower layers.

> **Auto-generated -- do not edit the region between the markers below.**
> Regenerate by replacing this file with the `cmake-target-layers` artifact from the
> *Verify CMake target layers* CI run, or locally with the full CI toolchain via
> `python3 scripts/cmake_target_layers.py --preset ci-linux --write`.
> CI fails when the committed diagram drifts from what CMake reports.

<!-- BEGIN GENERATED: cmake-target-layers (do not edit by hand) -->

## Overview

- **59** targets, **98** direct dependencies, **8** layers.
- Generated from configure preset `ci-linux` (see `CMakePresets.json`).
- Layer *k* contains targets whose deepest direct-dependency chain is *k* long; every dependency points to a strictly lower layer, so there are **no edges within a layer**. This is a layered DAG (shared foundations create diamonds), not a strict tree.
- Raw system library links (`-ldl`, `-lstdc++fs`, …) are omitted: CMake records them as *Unknown library* nodes (not real CMake targets) and they carry no structural information about module boundaries.
- Third-party nodes that no first-party target links directly are omitted (e.g. `pybind11::pybind11`, `Catch2`, `ProjectConfig`). Only the top-level API surface that this project actually links against is shown; internal sub-targets of third-party packages are implementation details of those packages. A small set of individually-named build-machinery targets (see `HIDDEN_TARGETS` in the generator script) are also omitted — these are programmatically injected by CMake helper functions and do not represent user-authored dependency choices.
- **Transitive reduction applied:** edges that are already implied by a longer dependency path are omitted (e.g. if A → B → C, the redundant A → C edge is dropped). The graph has the same reachability as the raw CMake declarations; see the `CMakeLists.txt` files for every declared `target_link_libraries` call.

### Legend

- Node shape: `([executable])`, `[static / shared library]`, `[[module library]]`, `{{interface library}}`, `[/object library/]`, `[custom target]`.
- Node colour: blue = first-party target, grey = third-party dependency.
- Arrow `A --> B` means **A depends on B** (B is in a lower layer).
- Link visibility (`public` / `private` / `interface`) is listed in the per-target table below.

## Layered dependency graph

```mermaid
%%{init: {"flowchart": {"rankSpacing": 120}, "themeVariables": {"fontSize": "24pt"}} }%%
flowchart TD
  subgraph LYR7["Layer 7 - top (consumers)"]
    deviceio_session_py[["deviceio_session_py"]]
    viz_layers_tests(["viz_layers_tests"])
    viz_session_tests(["viz_session_tests"])
  end
  subgraph LYR6["Layer 6"]
    deviceio__deviceio_py_utils{{"deviceio::deviceio_py_utils"}}
    controller_synthetic_hands(["controller_synthetic_hands"])
    frame_metadata_printer(["frame_metadata_printer"])
    mcap_tests(["mcap_tests"])
    oxr_session_sharing(["oxr_session_sharing"])
    oxr_simple_api_demo(["oxr_simple_api_demo"])
    pedal_printer(["pedal_printer"])
    replay_deviceio_session_tests(["replay_deviceio_session_tests"])
    teleop_ros2_mcap_generator(["teleop_ros2_mcap_generator"])
    viz__layers_testing["viz::layers_testing"]
    viz_py[["viz_py"]]
  end
  subgraph LYR5["Layer 5"]
    deviceio__deviceio_session["deviceio::deviceio_session"]
    viz__layers["viz::layers"]
  end
  subgraph LYR4["Layer 4"]
    deviceio__live_trackers["deviceio::live_trackers"]
    deviceio__replay_trackers["deviceio::replay_trackers"]
    deviceio_trackers_py[["deviceio_trackers_py"]]
    viz__session["viz::session"]
    viz_xr_tests(["viz_xr_tests"])
    viz_core_tests(["viz_core_tests"])
  end
  subgraph LYR3["Layer 3"]
    deviceio__deviceio_trackers["deviceio::deviceio_trackers"]
    camera_plugin_oak(["camera_plugin_oak"])
    generic_3axis_pedal_plugin(["generic_3axis_pedal_plugin"])
    pedal_pusher(["pedal_pusher"])
    oxr_py[["oxr_py"]]
    viz__xr["viz::xr"]
    viz__test_support{{"viz::test_support"}}
    xdev_list(["xdev_list"])
  end
  subgraph LYR2["Layer 2"]
    pusherio__pusherio["pusherio::pusherio"]
    deviceio__deviceio_base{{"deviceio::deviceio_base"}}
    oxr__oxr_core["oxr::oxr_core"]
    mcap__mcap_core{{"mcap::mcap_core"}}
    schema_py[["schema_py"]]
    Teleop__plugin_utils["Teleop::plugin_utils"]
    viz__core["viz::core"]
    examples_common["examples_common"]
    plugin_manager_py[["plugin_manager_py"]]
    schema_tests(["schema_tests"])
    viz_shaders_tests(["viz_shaders_tests"])
  end
  subgraph LYR1["Layer 1"]
    oxr__oxr_utils{{"oxr::oxr_utils"}}
    isaacteleop_schema{{"isaacteleop_schema"}}
    OpenXR__openxr_loader["OpenXR::openxr_loader"]
    teleop_plugin_manager["teleop_plugin_manager"]
    depthai__core["depthai::core"]
    glfw["glfw"]
    Catch2__Catch2WithMain["Catch2::Catch2WithMain"]
  end
  subgraph LYR0["Layer 0 - foundation"]
    OpenXR__headers{{"OpenXR::headers"}}
    flatbuffers["flatbuffers"]
    yaml_cpp__yaml_cpp["yaml-cpp::yaml-cpp"]
    Threads__Threads{{"Threads::Threads"}}
    Catch2__Catch2["Catch2::Catch2"]
    SDL2__SDL2_static["SDL2::SDL2-static"]
    glm__glm{{"glm::glm"}}
    mcap__mcap{{"mcap::mcap"}}
    pybind11__module{{"pybind11::module"}}
    Teleop__openxr_extensions{{"Teleop::openxr_extensions"}}
    viz__shaders{{"viz::shaders"}}
  end
  Catch2__Catch2WithMain --> Catch2__Catch2
  camera_plugin_oak --> SDL2__SDL2_static
  camera_plugin_oak --> depthai__core
  camera_plugin_oak --> isaacteleop_schema
  camera_plugin_oak --> mcap__mcap
  camera_plugin_oak --> oxr__oxr_core
  camera_plugin_oak --> pusherio__pusherio
  controller_synthetic_hands --> deviceio__deviceio_session
  controller_synthetic_hands --> oxr__oxr_core
  controller_synthetic_hands --> Teleop__plugin_utils
  depthai__core --> Threads__Threads
  deviceio__deviceio_base --> isaacteleop_schema
  deviceio__deviceio_py_utils --> deviceio__deviceio_session
  deviceio__deviceio_session --> deviceio__live_trackers
  deviceio__deviceio_session --> deviceio__replay_trackers
  deviceio_session_py --> deviceio__deviceio_py_utils
  deviceio_session_py --> pybind11__module
  deviceio__deviceio_trackers --> deviceio__deviceio_base
  deviceio_trackers_py --> deviceio__deviceio_trackers
  deviceio_trackers_py --> pybind11__module
  examples_common --> OpenXR__openxr_loader
  frame_metadata_printer --> deviceio__deviceio_session
  frame_metadata_printer --> oxr__oxr_core
  generic_3axis_pedal_plugin --> isaacteleop_schema
  generic_3axis_pedal_plugin --> oxr__oxr_core
  generic_3axis_pedal_plugin --> pusherio__pusherio
  glfw --> Threads__Threads
  isaacteleop_schema --> flatbuffers
  deviceio__live_trackers --> deviceio__deviceio_trackers
  deviceio__live_trackers --> mcap__mcap_core
  deviceio__live_trackers --> oxr__oxr_utils
  deviceio__live_trackers --> Teleop__openxr_extensions
  mcap__mcap_core --> isaacteleop_schema
  mcap__mcap_core --> mcap__mcap
  mcap_tests --> Catch2__Catch2WithMain
  mcap_tests --> deviceio__deviceio_session
  OpenXR__openxr_loader --> Threads__Threads
  OpenXR__openxr_loader --> OpenXR__headers
  oxr__oxr_core --> OpenXR__openxr_loader
  oxr__oxr_core --> oxr__oxr_utils
  oxr_py --> oxr__oxr_core
  oxr_py --> pybind11__module
  oxr_session_sharing --> deviceio__deviceio_session
  oxr_session_sharing --> oxr__oxr_core
  oxr_simple_api_demo --> deviceio__deviceio_session
  oxr_simple_api_demo --> oxr__oxr_core
  oxr__oxr_utils --> OpenXR__headers
  pedal_printer --> deviceio__deviceio_session
  pedal_printer --> oxr__oxr_core
  pedal_pusher --> isaacteleop_schema
  pedal_pusher --> oxr__oxr_core
  pedal_pusher --> pusherio__pusherio
  plugin_manager_py --> pybind11__module
  plugin_manager_py --> teleop_plugin_manager
  pusherio__pusherio --> oxr__oxr_utils
  pusherio__pusherio --> Teleop__openxr_extensions
  replay_deviceio_session_tests --> Catch2__Catch2WithMain
  replay_deviceio_session_tests --> deviceio__deviceio_session
  deviceio__replay_trackers --> deviceio__deviceio_trackers
  deviceio__replay_trackers --> mcap__mcap_core
  schema_py --> isaacteleop_schema
  schema_py --> pybind11__module
  schema_tests --> Catch2__Catch2WithMain
  schema_tests --> OpenXR__headers
  schema_tests --> isaacteleop_schema
  teleop_plugin_manager --> Threads__Threads
  teleop_plugin_manager --> yaml_cpp__yaml_cpp
  Teleop__plugin_utils --> OpenXR__openxr_loader
  Teleop__plugin_utils --> oxr__oxr_utils
  Teleop__plugin_utils --> Teleop__openxr_extensions
  teleop_ros2_mcap_generator --> deviceio__deviceio_session
  viz__core --> glm__glm
  viz__core --> OpenXR__openxr_loader
  viz_core_tests --> Catch2__Catch2WithMain
  viz_core_tests --> viz__test_support
  viz__layers --> viz__session
  viz__layers --> viz__shaders
  viz__layers_testing --> viz__layers
  viz_layers_tests --> Catch2__Catch2WithMain
  viz_layers_tests --> viz__layers_testing
  viz_layers_tests --> viz__test_support
  viz_py --> pybind11__module
  viz_py --> viz__layers
  viz__session --> glfw
  viz__session --> oxr__oxr_utils
  viz__session --> viz__xr
  viz_session_tests --> Catch2__Catch2WithMain
  viz_session_tests --> viz__layers_testing
  viz_session_tests --> viz__test_support
  viz_shaders_tests --> Catch2__Catch2WithMain
  viz_shaders_tests --> viz__shaders
  viz__test_support --> Catch2__Catch2
  viz__test_support --> viz__core
  viz__xr --> viz__core
  viz_xr_tests --> Catch2__Catch2WithMain
  viz_xr_tests --> viz__xr
  xdev_list --> examples_common
  xdev_list --> Teleop__openxr_extensions
  classDef firstparty fill:#d9e8fb,stroke:#3b73b9,color:#0b2545;
  classDef thirdparty fill:#ededed,stroke:#9a9a9a,color:#333333;
  class Teleop__openxr_extensions,Teleop__plugin_utils,camera_plugin_oak,controller_synthetic_hands,deviceio__deviceio_base,deviceio__deviceio_py_utils,deviceio__deviceio_session,deviceio__deviceio_trackers,deviceio__live_trackers,deviceio__replay_trackers,deviceio_session_py,deviceio_trackers_py,examples_common,frame_metadata_printer,generic_3axis_pedal_plugin,isaacteleop_schema,mcap__mcap,mcap__mcap_core,mcap_tests,oxr__oxr_core,oxr__oxr_utils,oxr_py,oxr_session_sharing,oxr_simple_api_demo,pedal_printer,pedal_pusher,plugin_manager_py,pusherio__pusherio,replay_deviceio_session_tests,schema_py,schema_tests,teleop_plugin_manager,teleop_ros2_mcap_generator,viz__core,viz__layers,viz__layers_testing,viz__session,viz__shaders,viz__test_support,viz__xr,viz_core_tests,viz_layers_tests,viz_py,viz_session_tests,viz_shaders_tests,viz_xr_tests,xdev_list firstparty
  class Catch2__Catch2,Catch2__Catch2WithMain,OpenXR__headers,OpenXR__openxr_loader,SDL2__SDL2_static,Threads__Threads,depthai__core,flatbuffers,glfw,glm__glm,pybind11__module,yaml_cpp__yaml_cpp thirdparty
```

## Layers

| Layer | Targets |
| ----: | ------- |
| 7 | `deviceio_session_py`, `viz_layers_tests`, `viz_session_tests` |
| 6 | `deviceio::deviceio_py_utils`, `controller_synthetic_hands`, `frame_metadata_printer`, `mcap_tests`, `oxr_session_sharing`, `oxr_simple_api_demo`, `pedal_printer`, `replay_deviceio_session_tests`, `teleop_ros2_mcap_generator`, `viz::layers_testing`, `viz_py` |
| 5 | `deviceio::deviceio_session`, `viz::layers` |
| 4 | `deviceio::live_trackers`, `deviceio::replay_trackers`, `deviceio_trackers_py`, `viz::session`, `viz_xr_tests`, `viz_core_tests` |
| 3 | `deviceio::deviceio_trackers`, `camera_plugin_oak`, `generic_3axis_pedal_plugin`, `pedal_pusher`, `oxr_py`, `viz::xr`, `viz::test_support`, `xdev_list` |
| 2 | `pusherio::pusherio`, `deviceio::deviceio_base`, `oxr::oxr_core`, `mcap::mcap_core`, `schema_py`, `Teleop::plugin_utils`, `viz::core`, `examples_common`, `plugin_manager_py`, `schema_tests`, `viz_shaders_tests` |
| 1 | `oxr::oxr_utils`, `isaacteleop_schema`, `OpenXR::openxr_loader`, `teleop_plugin_manager`, `depthai::core`, `glfw`, `Catch2::Catch2WithMain` |
| 0 | `OpenXR::headers`, `flatbuffers`, `yaml-cpp::yaml-cpp`, `Threads::Threads`, `Catch2::Catch2`, `SDL2::SDL2-static`, `glm::glm`, `mcap::mcap`, `pybind11::module`, `Teleop::openxr_extensions`, `viz::shaders` |

## Direct dependencies by target

| Target | Type | Origin | Layer | Direct dependencies |
| ------ | ---- | ------ | ----: | ------------------- |
| `Catch2::Catch2` | Static library | third-party | 0 | _(none)_ |
| `Catch2::Catch2WithMain` | Static library | third-party | 1 | `Catch2::Catch2` (public) |
| `SDL2::SDL2-static` | Static library | third-party | 0 | _(none)_ |
| `Threads::Threads` | Interface library | third-party | 0 | _(none)_ |
| `camera_plugin_oak` | Executable | first-party | 3 | `SDL2::SDL2-static` (private), `depthai::core` (private), `isaacteleop_schema` (private), `mcap::mcap` (private), `oxr::oxr_core` (private), `pusherio::pusherio` (private) |
| `controller_synthetic_hands` | Executable | first-party | 6 | `deviceio::deviceio_session` (private), `oxr::oxr_core` (private), `Teleop::plugin_utils` (private) |
| `depthai::core` | Static library | third-party | 1 | `Threads::Threads` (private) |
| `deviceio::deviceio_base` | Interface library | first-party | 2 | `isaacteleop_schema` (interface) |
| `deviceio::deviceio_py_utils` | Interface library | first-party | 6 | `deviceio::deviceio_session` (interface) |
| `deviceio::deviceio_session` | Static library | first-party | 5 | `deviceio::live_trackers` (private), `deviceio::replay_trackers` (private) |
| `deviceio_session_py` | Module library | first-party | 7 | `deviceio::deviceio_py_utils` (private), `pybind11::module` (private) |
| `deviceio::deviceio_trackers` | Static library | first-party | 3 | `deviceio::deviceio_base` (public) |
| `deviceio_trackers_py` | Module library | first-party | 4 | `deviceio::deviceio_trackers` (private), `pybind11::module` (private) |
| `examples_common` | Static library | first-party | 2 | `OpenXR::openxr_loader` (public) |
| `flatbuffers` | Static library | third-party | 0 | _(none)_ |
| `frame_metadata_printer` | Executable | first-party | 6 | `deviceio::deviceio_session` (private), `oxr::oxr_core` (private) |
| `generic_3axis_pedal_plugin` | Executable | first-party | 3 | `isaacteleop_schema` (private), `oxr::oxr_core` (private), `pusherio::pusherio` (private) |
| `glfw` | Static library | third-party | 1 | `Threads::Threads` (private) |
| `glm::glm` | Interface library | third-party | 0 | _(none)_ |
| `OpenXR::headers` | Interface library | third-party | 0 | _(none)_ |
| `isaacteleop_schema` | Interface library | first-party | 1 | `flatbuffers` (interface) |
| `deviceio::live_trackers` | Static library | first-party | 4 | `deviceio::deviceio_trackers` (public), `mcap::mcap_core` (public), `oxr::oxr_utils` (public), `Teleop::openxr_extensions` (public) |
| `mcap::mcap_core` | Interface library | first-party | 2 | `isaacteleop_schema` (interface), `mcap::mcap` (interface) |
| `mcap::mcap` | Interface library | first-party | 0 | _(none)_ |
| `mcap_tests` | Executable | first-party | 6 | `Catch2::Catch2WithMain` (private), `deviceio::deviceio_session` (private) |
| `OpenXR::openxr_loader` | Static library | third-party | 1 | `Threads::Threads` (public), `OpenXR::headers` (public) |
| `oxr::oxr_core` | Static library | first-party | 2 | `OpenXR::openxr_loader` (public), `oxr::oxr_utils` (public) |
| `oxr_py` | Module library | first-party | 3 | `oxr::oxr_core` (private), `pybind11::module` (private) |
| `oxr_session_sharing` | Executable | first-party | 6 | `deviceio::deviceio_session` (private), `oxr::oxr_core` (private) |
| `oxr_simple_api_demo` | Executable | first-party | 6 | `deviceio::deviceio_session` (private), `oxr::oxr_core` (private) |
| `oxr::oxr_utils` | Interface library | first-party | 1 | `OpenXR::headers` (interface) |
| `pedal_printer` | Executable | first-party | 6 | `deviceio::deviceio_session` (private), `oxr::oxr_core` (private) |
| `pedal_pusher` | Executable | first-party | 3 | `isaacteleop_schema` (private), `oxr::oxr_core` (private), `pusherio::pusherio` (private) |
| `plugin_manager_py` | Module library | first-party | 2 | `pybind11::module` (private), `teleop_plugin_manager` (private) |
| `pusherio::pusherio` | Static library | first-party | 2 | `oxr::oxr_utils` (public), `Teleop::openxr_extensions` (public) |
| `pybind11::module` | Interface library | third-party | 0 | _(none)_ |
| `replay_deviceio_session_tests` | Executable | first-party | 6 | `Catch2::Catch2WithMain` (private), `deviceio::deviceio_session` (private) |
| `deviceio::replay_trackers` | Static library | first-party | 4 | `deviceio::deviceio_trackers` (public), `mcap::mcap_core` (public) |
| `schema_py` | Module library | first-party | 2 | `isaacteleop_schema` (private), `pybind11::module` (private) |
| `schema_tests` | Executable | first-party | 2 | `Catch2::Catch2WithMain` (private), `OpenXR::headers` (private), `isaacteleop_schema` (private) |
| `Teleop::openxr_extensions` | Interface library | first-party | 0 | _(none)_ |
| `teleop_plugin_manager` | Static library | first-party | 1 | `Threads::Threads` (public), `yaml-cpp::yaml-cpp` (private) |
| `Teleop::plugin_utils` | Static library | first-party | 2 | `OpenXR::openxr_loader` (public), `oxr::oxr_utils` (public), `Teleop::openxr_extensions` (public) |
| `teleop_ros2_mcap_generator` | Executable | first-party | 6 | `deviceio::deviceio_session` (private) |
| `viz::core` | Static library | first-party | 2 | `glm::glm` (public), `OpenXR::openxr_loader` (public) |
| `viz_core_tests` | Executable | first-party | 4 | `Catch2::Catch2WithMain` (private), `viz::test_support` (private) |
| `viz::layers` | Static library | first-party | 5 | `viz::session` (public), `viz::shaders` (private) |
| `viz::layers_testing` | Static library | first-party | 6 | `viz::layers` (public) |
| `viz_layers_tests` | Executable | first-party | 7 | `Catch2::Catch2WithMain` (private), `viz::layers_testing` (private), `viz::test_support` (private) |
| `viz_py` | Module library | first-party | 6 | `pybind11::module` (private), `viz::layers` (private) |
| `viz::session` | Static library | first-party | 4 | `glfw` (public), `oxr::oxr_utils` (public), `viz::xr` (public) |
| `viz_session_tests` | Executable | first-party | 7 | `Catch2::Catch2WithMain` (private), `viz::layers_testing` (private), `viz::test_support` (private) |
| `viz::shaders` | Interface library | first-party | 0 | _(none)_ |
| `viz_shaders_tests` | Executable | first-party | 2 | `Catch2::Catch2WithMain` (private), `viz::shaders` (private) |
| `viz::test_support` | Interface library | first-party | 3 | `Catch2::Catch2` (interface), `viz::core` (interface) |
| `viz::xr` | Static library | first-party | 3 | `viz::core` (public) |
| `viz_xr_tests` | Executable | first-party | 4 | `Catch2::Catch2WithMain` (private), `viz::xr` (private) |
| `xdev_list` | Executable | first-party | 3 | `examples_common` (private), `Teleop::openxr_extensions` (private) |
| `yaml-cpp::yaml-cpp` | Static library | third-party | 0 | _(none)_ |

<!-- END GENERATED: cmake-target-layers -->
