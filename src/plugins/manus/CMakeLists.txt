# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

include(GNUInstallDirs)

option(MANUS_ADD_SDK_TO_BUILD_RPATH "Add Manus SDK lib dir to BUILD_RPATH for plugin and tools" ON)

# -------------------------------------------------------------------------------------------------
# 1. SDK Detection Logic
# -------------------------------------------------------------------------------------------------

set(_MANUS_REAL_SDK_FOUND OFF)
set(_MANUS_REAL_SDK_ROOT "")

# Check common locations for Real SDK
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/ManusSDK/include/ManusSDK.h")
  set(_MANUS_REAL_SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/ManusSDK")
  set(_MANUS_REAL_SDK_FOUND ON)
elseif(EXISTS "${CMAKE_SOURCE_DIR}/ManusSDK/include/ManusSDK.h")
  set(_MANUS_REAL_SDK_ROOT "${CMAKE_SOURCE_DIR}/ManusSDK")
  set(_MANUS_REAL_SDK_FOUND ON)
elseif(DEFINED ENV{MANUS_SDK_ROOT} AND EXISTS "$ENV{MANUS_SDK_ROOT}/include/ManusSDK.h")
  set(_MANUS_REAL_SDK_ROOT "$ENV{MANUS_SDK_ROOT}")
  set(_MANUS_REAL_SDK_FOUND ON)
endif()

# -------------------------------------------------------------------------------------------------
# 2. Decision & Configuration Logic
# -------------------------------------------------------------------------------------------------

set(USING_MOCK_SDK OFF)

if(_MANUS_REAL_SDK_FOUND)
  # If we found the real SDK, always prefer it.
  # Update cache if it was previously set to something else (e.g. mocks)
  set(MANUS_SDK_ROOT "${_MANUS_REAL_SDK_ROOT}" CACHE PATH "Path to Manus SDK root" FORCE)
  message(STATUS "Found Manus SDK at: ${MANUS_SDK_ROOT}")
else()
  # Real SDK not found. Fallback to Mocks.
  set(USING_MOCK_SDK ON)
  message(WARNING "Real Manus SDK not found. Building against Mock SDK for testing/development.")

  # Point to mock headers for downstream include checks
  set(MANUS_SDK_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/tests/mock_headers/ManusSDK" CACHE PATH "Path to Manus SDK root" FORCE)
endif()

set(MANUS_SDK_INCLUDE_DIR "${MANUS_SDK_ROOT}/include" CACHE PATH "Manus SDK include path" FORCE)

# -------------------------------------------------------------------------------------------------
# 3. Setup Targets
# -------------------------------------------------------------------------------------------------

if(NOT USING_MOCK_SDK)
  # -----------------------------------------------------------------------
  # Real SDK Setup
  # -----------------------------------------------------------------------

  set(_MANUS_LIBDIR_CANDIDATES
    "${MANUS_SDK_ROOT}/lib"
    "${MANUS_SDK_ROOT}/lib64"
  )
  set(_MANUS_LIBDIR "")
  foreach(_cand IN LISTS _MANUS_LIBDIR_CANDIDATES)
    if(EXISTS "${_cand}")
      set(_MANUS_LIBDIR "${_cand}")
      break()
    endif()
  endforeach()
  if(NOT _MANUS_LIBDIR)
    set(_MANUS_LIBDIR "${MANUS_SDK_ROOT}/lib")
  endif()
  set(MANUS_SDK_LIBRARY_DIR "${_MANUS_LIBDIR}" CACHE PATH "Manus SDK library path" FORCE)

  set(MANUS_SHOULD_BUILD ON)
  set(MANUS_SKIP_REASON "")

  if(NOT EXISTS "${MANUS_SDK_INCLUDE_DIR}/ManusSDK.h")
    set(MANUS_SHOULD_BUILD OFF)
    set(MANUS_SKIP_REASON "Headers not found in ${MANUS_SDK_INCLUDE_DIR}")
  endif()

  if(MANUS_SHOULD_BUILD)
    if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK.so")
      if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK_Integrated.so")
        set(MANUS_SHOULD_BUILD OFF)
        set(MANUS_SKIP_REASON "Libraries not found in ${MANUS_SDK_LIBRARY_DIR}")
      endif()
    endif()
  endif()

  set(_MANUS_LIB "")
  if(MANUS_SHOULD_BUILD)
    set(_MANUS_CANDIDATES
      "${MANUS_SDK_LIBRARY_DIR}/libManusSDK_Integrated.so"
      "${MANUS_SDK_LIBRARY_DIR}/libManusSDK.so"
    )
    foreach(_cand IN LISTS _MANUS_CANDIDATES)
      if(EXISTS "${_cand}")
        set(_MANUS_LIB "${_cand}")
        break()
      endif()
    endforeach()
    if(NOT _MANUS_LIB)
      set(MANUS_SHOULD_BUILD OFF)
      set(MANUS_SKIP_REASON "No shared library found under ${MANUS_SDK_LIBRARY_DIR}")
    endif()
  endif()

  if(NOT MANUS_SHOULD_BUILD)
    message(STATUS "Skipping Manus plugin build: ${MANUS_SKIP_REASON}")
    add_custom_target(isaac_manus_plugin COMMAND ${CMAKE_COMMAND} -E echo "Skipping isaac_manus_plugin: ${MANUS_SKIP_REASON}")
    add_custom_target(manus_hand_plugin COMMAND ${CMAKE_COMMAND} -E echo "Skipping manus_hand_plugin: ${MANUS_SKIP_REASON}")
    add_custom_target(ManusHandTrackerPrinter COMMAND ${CMAKE_COMMAND} -E echo "Skipping ManusHandTrackerPrinter: ${MANUS_SKIP_REASON}")
    return()
  endif()

  # Create imported library target for Manus SDK
  add_library(ManusSDK::ManusSDK SHARED IMPORTED)

  get_filename_component(_MANUS_LIB_NAME "${_MANUS_LIB}" NAME)

  set_target_properties(ManusSDK::ManusSDK PROPERTIES
    IMPORTED_LOCATION "${_MANUS_LIB}"
    IMPORTED_SONAME "${_MANUS_LIB_NAME}"
    IMPORTED_NO_SONAME TRUE
    INTERFACE_INCLUDE_DIRECTORIES "${MANUS_SDK_INCLUDE_DIR}"
  )

  set(_ISAAC_MANUS_BASE_BUILD_RPATH "$ORIGIN;$ORIGIN/../lib")
  set(_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${_ISAAC_MANUS_BASE_BUILD_RPATH}")
  if(MANUS_ADD_SDK_TO_BUILD_RPATH)
    list(APPEND _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${MANUS_SDK_LIBRARY_DIR}")
  endif()
  list(JOIN _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH ";" _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR)

else()
  # -----------------------------------------------------------------------
  # Mock SDK Setup
  # -----------------------------------------------------------------------

  # Build the mock implementation into a shared library
  add_library(ManusSDK_Mock SHARED
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/mock_env.cpp"
  )

  target_include_directories(ManusSDK_Mock PUBLIC
    "${MANUS_SDK_INCLUDE_DIR}"
  )
  target_include_directories(ManusSDK_Mock PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/tests" # For mock_env.hpp
  )

  # Try to link against OpenXR headers if available in main project to ensure type compatibility
  # If not available, we might need to fallback to mock openxr headers, but let's assume
  # the main project provides OpenXR (e.g. via Teleop::openxr_extensions or OpenXR::headers)
  if(TARGET OpenXR::headers)
      target_link_libraries(ManusSDK_Mock PRIVATE OpenXR::headers)
  elseif(TARGET OpenXR::openxr_loader)
      target_link_libraries(ManusSDK_Mock PRIVATE OpenXR::openxr_loader)
  else()
      # Fallback: Use our mock OpenXR headers if real ones aren't found
      target_include_directories(ManusSDK_Mock PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/tests/mock_headers")
  endif()

  # Alias to standard name
  add_library(ManusSDK::ManusSDK ALIAS ManusSDK_Mock)

  # RPATH handling for mock (standard RPATH is fine)
  set(_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR "$ORIGIN;$ORIGIN/../lib")

endif()

# -------------------------------------------------------------------------------------------------
# 4. Build Targets
# -------------------------------------------------------------------------------------------------

add_subdirectory(core)
add_library(isaac::manus_plugin ALIAS isaac_manus_plugin)
add_subdirectory(app)
add_subdirectory(tools)

# -------------------------------------------------------------------------------------------------
# 5. Install
# -------------------------------------------------------------------------------------------------

# Only install the vendor library if it's the Real SDK
if(NOT USING_MOCK_SDK)
  install(FILES "${_MANUS_LIB}"
      DESTINATION ${CMAKE_INSTALL_LIBDIR}
  )
endif()
