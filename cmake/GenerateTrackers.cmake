# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

function(isaac_teleop_generate_trackers)
  set(_TRACKER_MANIFEST "${CMAKE_SOURCE_DIR}/src/core/deviceio_trackers/trackers.toml")
  set(_TRACKER_DEFAULTS "${CMAKE_SOURCE_DIR}/src/core/deviceio_trackers/defaults.toml")
  set(_GENERATOR "${CMAKE_SOURCE_DIR}/src/core/codegen/generate_trackers.py")
  set(_CODEGEN_TEMPLATES_DIR "${CMAKE_SOURCE_DIR}/src/core/codegen/templates")
  file(GLOB_RECURSE _CODEGEN_IN_TEMPLATES CONFIGURE_DEPENDS
       "${_CODEGEN_TEMPLATES_DIR}/*.template")
  set(_OUT_DIR "${CMAKE_BINARY_DIR}/generated/trackers")
  set(_CMAKE_OUT "${_OUT_DIR}/generated_sources.cmake")

  # Pass --prune-stale so renamed/removed trackers cannot leave orphan headers that
  # still satisfy stale #includes on the generated include path.
  execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${_GENERATOR}"
            --manifest "${_TRACKER_MANIFEST}"
            --defaults "${_TRACKER_DEFAULTS}"
            --out-dir "${_OUT_DIR}"
            --emit-cmake "${_CMAKE_OUT}"
            --prune-stale
    RESULT_VARIABLE _tracker_gen_rc
    OUTPUT_VARIABLE _tracker_gen_out
    ERROR_VARIABLE _tracker_gen_err)
  if(NOT _tracker_gen_rc EQUAL 0)
    message(FATAL_ERROR "tracker codegen failed:\n${_tracker_gen_out}\n${_tracker_gen_err}")
  endif()

  include("${_CMAKE_OUT}")
  set(GENERATED_TRACKER_DIR "${GENERATED_TRACKER_DIR}" PARENT_SCOPE)
  set(GENERATED_TRACKER_FACADE_SOURCES "${GENERATED_TRACKER_FACADE_SOURCES}" PARENT_SCOPE)
  set(GENERATED_TRACKER_LIVE_SOURCES "${GENERATED_TRACKER_LIVE_SOURCES}" PARENT_SCOPE)
  set(GENERATED_TRACKER_REPLAY_SOURCES "${GENERATED_TRACKER_REPLAY_SOURCES}" PARENT_SCOPE)
  set(GENERATED_TRACKER_DEVICEIO_BASE_INC_DIR "${GENERATED_TRACKER_DEVICEIO_BASE_INC_DIR}" PARENT_SCOPE)
  set(GENERATED_TRACKER_DEVICEIO_TRACKERS_INC_DIR "${GENERATED_TRACKER_DEVICEIO_TRACKERS_INC_DIR}" PARENT_SCOPE)
  set(GENERATED_TRACKER_LIVE_IMPL_INC_DIR "${GENERATED_TRACKER_LIVE_IMPL_INC_DIR}" PARENT_SCOPE)
  set(GENERATED_TRACKER_REPLAY_IMPL_INC_DIR "${GENERATED_TRACKER_REPLAY_IMPL_INC_DIR}" PARENT_SCOPE)
  set(GENERATED_TRACKER_INC_DIR "${GENERATED_TRACKER_INC_DIR}" PARENT_SCOPE)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
               "${_TRACKER_MANIFEST}" "${_TRACKER_DEFAULTS}" "${_GENERATOR}"
               "${CMAKE_SOURCE_DIR}/src/core/codegen/manifest.py"
               "${CMAKE_SOURCE_DIR}/src/core/codegen/templates.py"
               "${CMAKE_SOURCE_DIR}/src/core/codegen/template_renderer.py"
               ${_CODEGEN_IN_TEMPLATES})
endfunction()
